import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Semaphore
from typing import Dict, List, Optional, Tuple

from nornir.core.inventory import Host
from nornir.core.task import AggregatedResult, MultiResult, Result, Task

logger = logging.getLogger(__name__)


class ConditionalRunner:
    """A runner that enforces concurrency limits and failure thresholds based on host groups."""

    def __init__(
        self,
        num_workers: int = 100,
        group_limits: Optional[Dict[str, int]] = None,
        group_fail_limits: Optional[Dict[str, int]] = None,
        conditional_group_key: Optional[str] = None,
        skip_unspecified_group_on_failure: bool = True,
    ) -> None:
        """Initialize the ConditionalRunner with concurrency semaphores, failure counters and locks."""
        self.num_workers = num_workers
        self.group_limits = group_limits or {}
        # Copy so that defaults added later never leak into the caller's dict.
        self.group_fail_limits: Dict[str, int] = dict(group_fail_limits or {})
        self.group_key = conditional_group_key
        self.group_semaphores: Dict[str, Semaphore] = {}
        self.group_failures: Dict[str, int] = {}
        self.group_locks: Dict[str, Lock] = {}
        self.skip_unspecified_group_on_failure = skip_unspecified_group_on_failure
        # Guards lazy creation of per-group data structures.
        self._init_lock = Lock()

        for group, fail_limit in self.group_fail_limits.items():
            if not isinstance(fail_limit, int) or fail_limit <= 0:
                raise ValueError(
                    f"Invalid failure limit for group '{group}': {fail_limit}. "
                    "Limit must be a positive integer."
                )

        if not self.group_limits:
            logger.warning(
                "No group limits specified. Default limits will be applied to all groups."
            )
        else:
            for group, limit in self.group_limits.items():
                if not isinstance(limit, int) or limit <= 0:
                    raise ValueError(
                        f"Invalid limit for group '{group}': {limit}. Limit must be a positive integer."
                    )
                self._init_data_structures(group, limit)

    def _init_data_structures(self, group: str, limit: int) -> None:
        # The semaphore is published LAST: _ensure_group() uses its presence as the
        # "fully initialized" marker, so other threads never see a half-built group.
        self.group_failures[group] = 0
        self.group_locks[group] = Lock()
        if self.skip_unspecified_group_on_failure:
            self.group_fail_limits.setdefault(group, 1)
        self.group_semaphores[group] = Semaphore(limit)

    def _ensure_group(self, group: str) -> None:
        """Thread-safe lazy initialization for groups without an explicit limit."""
        if group in self.group_semaphores:
            return
        with self._init_lock:
            if group in self.group_semaphores:  # another thread won the race
                return
            logger.warning(
                f"No limit for group '{group}'. Using default limit of {self.num_workers}."
            )
            self._init_data_structures(group, self.num_workers)

    def run(self, task: Task, hosts: List[Host]) -> AggregatedResult:
        """Run the task for each host while respecting group-based concurrency limits."""
        logger.info("Running task with ConditionalRunner using semaphores")
        result = AggregatedResult(task.name)

        with ThreadPoolExecutor(self.num_workers) as pool:
            futures = []
            for host in hosts:
                host_groups = [group.name for group in host.groups]
                # If the group_key is in host.data, use it; otherwise, fall back to groups
                if self.group_key and self.group_key in host.data:
                    groups = host.data[self.group_key]
                else:
                    groups = host_groups
                    if self.group_key:
                        logger.warning(
                            f"Host '{host.name}' has no '{self.group_key}' attribute. Using groups instead."
                        )

                futures.append(
                    pool.submit(self._dispatch_task_and_wait, task, host, groups)
                )

            for future in futures:
                worker_result = future.result()
                if worker_result:
                    result[worker_result.host.name] = worker_result

        return result

    def _dispatch_task_and_wait(
        self, task: Task, host: Host, groups: List[str]
    ) -> MultiResult:
        """Prepare the host's groups and run the task in the current worker thread."""
        # Deduplicate and sort: acquiring semaphores in one global order prevents
        # deadlocks, and a duplicate group would otherwise make a host wait on itself.
        ordered_groups = sorted({str(group) for group in groups})
        for group in ordered_groups:
            self._ensure_group(group)
        return self._run_task_with_semaphores(task, host, ordered_groups)

    def _exhausted_group(self, groups: List[str]) -> Optional[Tuple[str, int]]:
        """Return (group, limit) for the first group that reached its failure limit."""
        for group in groups:
            fail_limit = self.group_fail_limits.get(group)
            if fail_limit is None:
                continue
            with self.group_locks[group]:
                if self.group_failures[group] >= fail_limit:
                    return group, fail_limit
        return None

    @staticmethod
    def _skipped_result(host: Host, group: str, fail_limit: int) -> MultiResult:
        logger.warning(
            f"Group '{group}' reached failure limit ({fail_limit}). Skipping host '{host.name}'."
        )
        result = MultiResult(name=host.name)
        result.append(
            Result(
                name="skipped",
                host=host,
                failed=True,
                exception=Exception(
                    f"Skipped due to failure limit for group '{group}'"
                ),
            )
        )
        return result

    def _run_task_with_semaphores(
        self, task: Task, host: Host, groups: List[str]
    ) -> MultiResult:
        """Run the task for a host while respecting group-based concurrency and tracking failures."""
        # Fast path: skip without queueing for a slot if a limit is already hit.
        exhausted = self._exhausted_group(groups)
        if exhausted:
            return self._skipped_result(host, *exhausted)

        acquired: List[str] = []
        try:
            # `groups` is sorted by the caller, so acquisition order is consistent.
            for group in groups:
                self.group_semaphores[group].acquire()
                acquired.append(group)

            # Re-check: failures may have accumulated while we waited for slots.
            exhausted = self._exhausted_group(groups)
            if exhausted:
                return self._skipped_result(host, *exhausted)

            result = task.copy().start(host)

            if result.failed:
                for group in groups:
                    with self.group_locks[group]:
                        self.group_failures[group] += 1
                        logger.debug(
                            f"Task failed for host '{host.name}' in group '{group}'. "
                            f"Total failures: {self.group_failures[group]}"
                        )

            return result

        finally:
            for group in reversed(acquired):
                self.group_semaphores[group].release()
