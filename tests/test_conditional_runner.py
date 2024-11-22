import unittest
from unittest.mock import MagicMock, Mock, patch
from threading import Semaphore, Condition
from nornir.core.inventory import Host
from nornir.core.task import Task, AggregatedResult, MultiResult, Result
import logging
from nornir_conditional_runner.conditional_runner import ConditionalRunner
from typing import List, Dict


# Disable logging to avoid clutter in the test output
logging.getLogger(__name__).disabled = True


class TestConditionalRunner(unittest.TestCase):
    """Unittest the ConditionalRunner class."""

    def setUp(self) -> None:
        """Set up the test environment."""
        self.group_limits: Dict[str, int] = {
            "core": 1,
            "edge": 2,
        }  # Define group limits
        self.runner: ConditionalRunner = ConditionalRunner(
            num_workers=2,
            group_limits=self.group_limits,
            conditional_group_key="conditional_groups",
        )

        # Mock task that simulates work
        self.task: Mock = Mock(spec=Task)
        self.task.name = "mock_task"
        self.task.copy.return_value = self.task
        self.task.start.side_effect = lambda host: MultiResult(
            f"Result for {host.name}"
        )

        # Define mock hosts with different groups
        self.hosts: List[Host] = [
            Host(name="core-01", data={"conditional_groups": ["core"]}),
            Host(name="core-02", data={"conditional_groups": ["core"]}),
            Host(name="edge-01", data={"conditional_groups": ["edge"]}),
            Host(name="edge-02", data={"conditional_groups": ["edge"]}),
            Host(name="edge-03", data={"conditional_groups": ["edge"]}),
        ]

    # Tests for initialization
    def test_initialization_with_valid_limits(self) -> None:
        """Test proper initialization with valid concurrency limits."""
        runner: ConditionalRunner = ConditionalRunner(
            num_workers=10,
            group_limits=self.group_limits,
            conditional_group_key="conditional_groups",
        )
        self.assertEqual(runner.num_workers, 10)
        self.assertEqual(runner.group_limits, self.group_limits)
        self.assertIsInstance(runner.group_semaphores["core"], Semaphore)
        self.assertIsInstance(runner.group_conditions["core"], Condition)

    def test_initialization_with_invalid_limits(self) -> None:
        """Test initialization with invalid group limits, expecting ValueError."""
        with self.assertRaises(ValueError):
            ConditionalRunner(group_limits={"core": -1})

        with self.assertRaises(ValueError):
            ConditionalRunner(num_workers=2, group_limits={"core": "x"})  # type: ignore[dict-item]

    # Tests for task execution
    @patch("nornir.core.task.Task")
    def test_run_with_limited_concurrency(self, mock_task: MagicMock) -> None:
        """Test running tasks with limited concurrency."""
        self.task = mock_task()
        self.task.name = "mock_task"
        runner: ConditionalRunner = ConditionalRunner(
            num_workers=2, group_limits={"default": 1}
        )

        with patch.object(
            runner,
            "_dispatch_task_and_wait",
            return_value=AggregatedResult(self.task.name),
        ) as mock_run_task:
            result: AggregatedResult = runner.run(self.task, self.hosts)
            mock_run_task.assert_called()
            self.assertIsInstance(result, AggregatedResult)
            self.assertEqual(result.name, "mock_task")

    @patch("threading.Semaphore.acquire")
    @patch("threading.Semaphore.release")
    def test_semaphore_acquisition_and_release(
        self, mock_release: MagicMock, mock_acquire: MagicMock
    ) -> None:
        """Verify semaphore acquisition and release for group-limited tasks."""
        runner: ConditionalRunner = ConditionalRunner(
            num_workers=3,
            group_limits=self.group_limits,
            conditional_group_key="conditional_groups",
        )
        host: Host = Host(name="host4", data={"conditional_groups": ["core"]})

        runner._run_task_with_semaphores(
            self.task, host, host.data["conditional_groups"]
        )
        mock_acquire.assert_called_once()
        mock_release.assert_called_once()

    @patch("nornir_conditional_runner.conditional_runner.ThreadPoolExecutor")
    def test_run_with_multiple_groups(self, mock_executor: MagicMock) -> None:
        """Test running tasks with multiple groups."""
        runner = ConditionalRunner(num_workers=3, group_limits={"core": 1, "edge": 2})

        mock_executor.return_value.__enter__.return_value.submit = MagicMock()
        mock_executor.return_value.__enter__.return_value.submit.return_value.result.return_value = AggregatedResult(
            "mock_task"
        )

        result = runner.run(self.task, self.hosts)

        # Test that the task was submitted to the executor
        self.assertEqual(
            mock_executor.return_value.__enter__.return_value.submit.call_count, 5
        )

        # Check the result aggregation
        self.assertIsInstance(result, AggregatedResult)
        self.assertEqual(result.name, "mock_task")

    # Tests for warnings
    def test_warning_for_missing_group_limit(self) -> None:
        """Test for logging warning when no group limit is specified."""
        with self.assertLogs("nornir_conditional_runner", level="WARNING") as log:
            runner: ConditionalRunner = ConditionalRunner(num_workers=5)
            runner.run(self.task, self.hosts)
            self.assertTrue(
                any("No group limits specified" in message for message in log.output)
            )

    def test_warning_for_missing_group_key(self) -> None:
        """Test warning when a host lacks the specified group key."""
        runner: ConditionalRunner = ConditionalRunner(
            num_workers=3,
            group_limits={"core": 1},
            conditional_group_key="custom_key",
        )

        hosts: List[Host] = [
            Host(name="host1", data={}),  # Missing 'custom_key'
            Host(name="host2", data={"custom_key": ["core"]}),
        ]

        with self.assertLogs("nornir_conditional_runner", level="WARNING") as log:
            runner.run(self.task, hosts)
            self.assertTrue(
                any(
                    "Host 'host1' has no 'custom_key' attribute" in message
                    for message in log.output
                )
            )

    @patch("nornir_conditional_runner.conditional_runner.logger")
    def test_warning_for_empty_group_limits(self, mock_logger: MagicMock) -> None:
        """Test that a warning is logged if no group limits are provided."""
        runner = ConditionalRunner(num_workers=3)

        runner.run(self.task, self.hosts)

        # Check if the warning was logged
        mock_logger.warning.assert_called_with(
            "No group limits specified. Default limits will be applied to all groups."
        )

    def test_missing_group_limit_for_host_group(self) -> None:
        """Test that a warning is logged if a host group is missing from group_limits."""
        runner = ConditionalRunner(
            num_workers=3,
            group_limits={"core": 1},
            conditional_group_key="conditional_groups",
        )

        hosts = [
            Host(
                name="host1", data={"conditional_groups": ["edge_bad"]}
            ),  # 'edge' is not in group_limits
            Host(name="host2", data={"conditional_groups": ["core"]}),
        ]

        with self.assertLogs("nornir_conditional_runner", level="WARNING") as log:
            runner.run(self.task, hosts)
            self.assertTrue(
                any(
                    "No limit for group 'edge_bad'. Using default limit of 3."
                    in message
                    for message in log.output
                )
            )

    @patch("nornir_conditional_runner.conditional_runner.logger")
    def test_warning_for_missing_group_in_host_data(
        self, mock_logger: MagicMock
    ) -> None:
        """Test that a warning is logged if a host does not contain the expected group key."""
        runner = ConditionalRunner(
            num_workers=2,
            group_limits={"core": 1},
            conditional_group_key="conditional_groups",
        )

        hosts = [
            Host(name="host1", data={}),  # Missing 'conditional_groups'
            Host(name="host2", data={"conditional_groups": ["core"]}),
        ]

        runner.run(self.task, hosts)

        # Check if the warning was logged for missing 'conditional_groups'
        mock_logger.warning.assert_called_with(
            "Host 'host1' has no 'conditional_groups' attribute. Using groups instead."
        )

    def test_empty_host_list(self) -> None:
        """Test that the runner handles an empty list of hosts."""
        runner = ConditionalRunner(num_workers=3, group_limits={"core": 1})

        hosts: list[Host] = []
        result = runner.run(self.task, hosts)

        # Check that the result is an empty AggregatedResult
        self.assertEqual(len(result), 0)

    @patch("nornir_conditional_runner.conditional_runner.ThreadPoolExecutor")
    def test_run_with_multiple_groups_fail_limits_no_failed_tasks(
        self, mock_executor: MagicMock
    ) -> None:
        """Test running tasks with multiple groups."""
        runner = ConditionalRunner(
            num_workers=3,
            group_limits={"core": 1, "edge": 2},
            group_fail_limits={"core": 1, "edge": 1},
        )

        mock_executor.return_value.__enter__.return_value.submit = MagicMock()
        mock_executor.return_value.__enter__.return_value.submit.return_value.result.return_value = AggregatedResult(
            "mock_task"
        )

        result = runner.run(self.task, self.hosts)

        # Test that the task was submitted to the executor
        self.assertEqual(
            mock_executor.return_value.__enter__.return_value.submit.call_count, 5
        )

        # Check the result aggregation
        self.assertIsInstance(result, AggregatedResult)
        self.assertEqual(result.name, "mock_task")


class TestConditionalRunnerFailedLimitFeature(unittest.TestCase):
    def setUp(self) -> None:
        """Set up common variables for tests."""
        self.task = MagicMock(spec=Task)
        self.task.name = "mock_task"
        self.task.copy.return_value.start.side_effect = self.mock_task_execution

    def mock_task_execution(self, host: Host) -> MultiResult:
        """Simulate task execution with failures."""
        result = MultiResult(name=host.name)
        if "fail" in host.name:
            result.append(
                Result(
                    name="mock_task",
                    host=host,
                    failed=True,
                    exception=Exception("Simulated task failure"),
                )
            )
        else:
            result.append(Result(name="mock_task", host=host, failed=False))
        return result

    def test_group_reaches_failure_limit(self) -> None:
        """Test that a warning is logged when a group reaches its failure limit."""
        runner = ConditionalRunner(
            num_workers=3,
            group_limits={"core": 1},
            group_fail_limits={"core": 2},  # Fail limit for 'core' is 2
            conditional_group_key="conditional_groups",
        )

        hosts = [
            Host(name="host1_fail", data={"conditional_groups": ["core"]}),
            Host(name="host2_fail", data={"conditional_groups": ["core"]}),
            Host(name="host3", data={"conditional_groups": ["core"]}),
        ]

        with self.assertLogs("nornir_conditional_runner", level="WARNING") as log:
            result = runner.run(self.task, hosts)
            self.assertEqual(len(result), 3)

            # Ensure the correct warning is logged
            self.assertTrue(
                any(
                    f"Group 'core' reached failure limit (2). Skipping host 'host3'."
                    in message
                    for message in log.output
                )
            )

        # Ensure host3 was skipped
        skipped_host = result.get("host3")
        self.assertIsNotNone(skipped_host)
        self.assertTrue(skipped_host.failed)
        self.assertEqual(
            str(skipped_host.exception),
            "Skipped due to failure limit for group 'core'",
        )

    @patch("nornir_conditional_runner.conditional_runner.ThreadPoolExecutor")
    def test_run_with_multiple_groups_fail_limits_with_failed_tasks(
        self, mock_executor: MagicMock
    ) -> None:
        """Test running tasks with multiple groups and enforcing fail limits."""
        runner = ConditionalRunner(
            num_workers=3,
            group_limits={"core": 1, "edge": 2},
            group_fail_limits={
                "core": 1,
                "edge": 1,
            },  # Stop further tasks in a group after 1 failure
        )

        # Simulate task results: some will fail
        def mock_task_result(host):
            mock_result = MagicMock(spec=AggregatedResult)
            mock_result.failed = host in {"core-01", "edge-01"}  # Fail specific hosts
            mock_result.name = f"mock_task_{host}"
            return mock_result

        # Mock the executor's behavior to return task results per host
        def mock_submit(task_func, *args, **kwargs):
            host = kwargs.get("host")
            hostname = host.name if hasattr(host, "name") else host
            return MagicMock(result=MagicMock(return_value=mock_task_result(hostname)))

        mock_executor.return_value.__enter__.return_value.submit.side_effect = (
            mock_submit
        )

        # Mock hosts with the expected format
        self.hosts = [
            MagicMock(name="core-01", data={"conditional_groups": ["core"]}),
            MagicMock(name="core-02", data={"conditional_groups": ["core"]}),
            MagicMock(name="edge-01", data={"conditional_groups": ["edge"]}),
            MagicMock(name="edge-02", data={"conditional_groups": ["edge"]}),
            MagicMock(name="edge-03", data={"conditional_groups": ["edge"]}),
        ]

        # Run the ConditionalRunner with the mock task and hosts
        result = runner.run(self.task, self.hosts)

        # Assert tasks were submitted for execution
        self.assertEqual(
            mock_executor.return_value.__enter__.return_value.submit.call_count, 5
        )

        # Verify group fail limits are enforced (e.g., tasks stop running after failures)
        for group, fail_limit in runner.group_fail_limits.items():
            failed_count = sum(
                mock_task_result(host.name).failed
                for host in self.hosts
                if group in host.data.get("conditional_groups", [])
            )
            self.assertLessEqual(
                failed_count, fail_limit, f"Exceeded fail limit for group {group}"
            )

        # Check the result aggregation
        self.assertIsInstance(result, AggregatedResult)
        self.assertEqual(result.name, "mock_task")

    def test_initialization_with_invalid_limits(self) -> None:
        """Test initialization with invalid group limits, expecting ValueError."""
        with self.assertRaises(ValueError):
            ConditionalRunner(group_limits={"core": 1}, group_fail_limits={"core": 0, "edge": -1})

        with self.assertRaises(ValueError):
            ConditionalRunner(num_workers=2, group_limits={"core": 1}, group_fail_limits={"core": "x"})  # type: ignore[dict-item]


if __name__ == "__main__":
    unittest.main()
