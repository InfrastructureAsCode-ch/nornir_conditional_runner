import logging
from concurrent.futures import ThreadPoolExecutor
from threading import Semaphore, Condition, Lock
from typing import Optional, List, Dict
from nornir.core.inventory import Host
from nornir.core.task import AggregatedResult, MultiResult, Task, Result

logger = logging.getLogger(__name__)

class ConditionalRunner:
    """A runner that enforces concurrency limits and failure thresholds based on host groups."""

    def __init__(
        self,
        num_workers: int = 100,
        group_limits: Optional[Dict[str, int]] = None,
        group_fail_limits: Optional[Dict[str, int]] = None,
        conditional_group_key: Optional[str] = None,
    ) -> None:
        """Initialize the ConditionalRunner with concurrency limit semaphores, failure counters, and conditions."""
        self.num_workers = num_workers
        self.group_limits = group_limits or {}
        self.group_fail_limits = group_fail_limits or {}
        self.group_key = conditional_group_key
        self.group_semaphores: Dict[str, Semaphore] = {}
        self.group_conditions: Dict[str, Condition] = {}
        self.group_failures: Dict[str, int] = {}
        self.group_locks: Dict[str, Lock] = {}

        if not self.group_limits:
            logger.warning(
                "No group limits specified. Default limits will be applied to all groups."
            )
        else:
            # Initialize semaphores, conditions, locks, and failure counters for each group
            for group, limit in self.group_limits.items():
                if not isinstance(limit, int) or limit <= 0:
                    raise ValueError(
                        f"Invalid limit for group '{group}': {limit}. Limit must be a positive integer."
                    )
                fail_limit = self.group_fail_limits.get(group)
                if fail_limit is not None and (not isinstance(fail_limit, int) or fail_limit <= 0):
                    raise ValueError(
                        f"Invalid failure limit for group '{group}': {self.group_fail_limits.get(group)}. Limit must be a positive integer."
                    )
                self.group_semaphores[group] = Semaphore(limit)
                self.group_conditions[group] = Condition()
                self.group_failures[group] = 0
                self.group_locks[group] = Lock()

    def run(self, task: Task, hosts: List[Host]) -> AggregatedResult:
        """Run the task for each host while respecting group-based concurrency limits."""
        logger.info("Running task with ConditionalRunner using semaphores")
        result = AggregatedResult(task.name)

        with ThreadPoolExecutor(self.num_workers) as pool:
            futures = []
            for host in hosts:
                # Get groups for the host
                groups = (
                    host.data.get(self.group_key, [group.name for group in host.groups])
                    if self.group_key
                    else [group.name for group in host.groups]
                )
                if groups == [group.name for group in host.groups] and self.group_key:
                    logger.warning(
                        f"Host '{host.name}' has no '{self.group_key}' attribute. Using groups instead."
                    )

                # Dispatch tasks to the thread pool
                futures.append(
                    pool.submit(self._dispatch_task_and_wait, task, host, groups)
                )

            # Wait for all futures to complete and collect the results
            for future in futures:
                worker_result = future.result()
                if worker_result:
                    result[worker_result.host.name] = worker_result

        return result

    def _dispatch_task_and_wait(
        self, task: Task, host: Host, groups: List[str]
    ) -> MultiResult:
        """Dispatch task in a separate thread and check failure limits."""
        # Check failure thresholds for all groups
        for group in groups:
            if str(group) not in self.group_semaphores:
                logger.warning(
                    f"No limit for group '{group}'. Using default limit of {self.num_workers}."
                )
                self.group_semaphores[group] = Semaphore(self.num_workers)
                self.group_conditions[group] = Condition()
                self.group_locks[group] = Lock()

            # Wait for each group's semaphore to be available
            with self.group_conditions[group]:
                while self.group_semaphores[group]._value <= 0:
                    self.group_conditions[group].wait()

        return self._run_task_with_semaphores(task, host, groups)

    def _run_task_with_semaphores(
        self, task: Task, host: Host, groups: List[str]
    ) -> MultiResult:
        """Run the task for a host while respecting group-based concurrency and tracking failures."""
        acquired_semaphores = []
        try:
            # Acquire semaphores for all groups the host belongs to
            for group in groups:
                self.group_semaphores[group].acquire()
                acquired_semaphores.append(group)

                # Check failure limits for this group *after acquiring the semaphore*
                fail_limit = self.group_fail_limits.get(group)
                with self.group_locks[group]:
                    if fail_limit is not None and self.group_failures[group] >= fail_limit:
                        logger.warning(
                            f"Group '{group}' reached failure limit ({fail_limit}). Skipping host '{host.name}'."
                        )
                        result = MultiResult(name=host.name)
                        result.append(Result(
                            name="skipped",
                            host=host,
                            failed=True,
                            exception=Exception(f"Skipped due to failure limit for group '{group}'")
                        ))
                        return result

            # Execute the task
            result = task.copy().start(host)

            if result.failed:
                # Increment failure counters for all groups
                for group in groups:
                    with self.group_locks[group]:
                        self.group_failures[group] += 1
                        logger.warning(
                            f"Task failed for host '{host.name}' in group '{group}'. Total failures: {self.group_failures[group]}"
                        )

            return result

        finally:
            # Always release semaphores, regardless of the task outcome
            for group in acquired_semaphores:
                self.group_semaphores[group].release()

            # Notify other threads waiting for semaphores
            for group in groups:
                with self.group_conditions[group]:
                    self.group_conditions[group].notify_all()
