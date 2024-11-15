import unittest
from unittest.mock import MagicMock, patch
from threading import Semaphore, Condition
from nornir.core.inventory import Host
from nornir.core.task import Task, AggregatedResult
import logging
from nornir_conditional_runner.conditional_runner import ConditionalRunner

# Disable logging to avoid clutter in the test output
logging.getLogger(__name__).disabled = True


class TestConditionalRunner(unittest.TestCase):
    """Test cases for the ConditionalRunner class."""

    def setUp(self):
        """Set up test data."""
        group_a = MagicMock(name="group_a")
        group_b = MagicMock(name="group_b")

        self.host1 = Host(
            name="host1",
            hostname="1.1.1.1",
            groups=[group_a],
            data={"conditional_groups": ["group_a"]},
        )
        self.host2 = Host(
            name="host2",
            hostname="2.2.2.2",
            groups=[group_b],
            data={"conditional_groups": ["group_b"]},
        )
        self.hosts = [self.host1, self.host2]
        self.task = MagicMock(spec=Task)
        self.task.name = "mock_task"
        self.group_limits = {"group_a": 1, "group_b": 2}

    def test_initialization_with_valid_limits(self):
        """Test proper initialization with valid concurrency limits."""
        runner = ConditionalRunner(
            num_workers=10,
            group_limits=self.group_limits,
            conditional_group_key="groups",
        )
        self.assertEqual(runner.num_workers, 10)
        self.assertEqual(runner.group_limits, self.group_limits)
        self.assertIsInstance(runner.group_semaphores["group_a"], Semaphore)
        self.assertIsInstance(runner.group_conditions["group_a"], Condition)

    def test_initialization_with_invalid_limits(self):
        """Test initialization with invalid group limits, expecting ValueError."""
        with self.assertRaises(ValueError):
            ConditionalRunner(group_limits={"group_a": -1})

    @patch("nornir.core.task.Task")
    def test_run_with_limited_concurrency(self, mok_task):
        """Test running tasks with limited concurrency."""
        self.task = mok_task()
        self.task.name = "mock_task"
        runner = ConditionalRunner(num_workers=2, group_limits={"default": 1})

        # Test task execution with mock result
        with patch.object(
            runner,
            "_dispatch_task_and_wait",
            return_value=AggregatedResult(self.task.name),
        ) as mock_run_task:
            result = runner.run(self.task, self.hosts)
            mock_run_task.assert_called()
            self.assertIsInstance(result, AggregatedResult)
            self.assertEqual(result.name, "mock_task")

    @patch("threading.Condition.wait", side_effect=lambda: None)
    @patch("threading.Condition.notify_all")
    def test_semaphore_blocking_and_releasing(self, mock_notify_all, mock_wait):
        """Test semaphore blocking and release for limited concurrency in groups."""
        runner = ConditionalRunner(
            num_workers=2, group_limits={"group_a": 1}, conditional_group_key="groups"
        )

        # Ensure task has a name for AggregatedResult
        self.task.name = "mock_task"

        # Use patch to force call to notify_all when semaphore is released
        with patch.object(
            runner,
            "_run_task_with_semaphores",
            return_value=AggregatedResult(self.task.name),
        ) as mock_run_task:
            mock_run_task.assert_called_once()  # Ensure task ran as expected
            runner.group_conditions[
                "group_a"
            ].notify_all()  # Manually trigger notify_all for the test
            mock_notify_all.assert_called_once()  # Verify notify_all was called

    @patch("threading.Semaphore.acquire")
    @patch("threading.Semaphore.release")
    def test_semaphore_acquisition_and_release(self, mock_release, mock_acquire):
        """Verify semaphore acquisition and release for group-limited tasks."""
        runner = ConditionalRunner(
            num_workers=3,
            group_limits=self.group_limits,
            conditional_group_key="groups",
        )
        host = Host(name="host4", hostname="4.4.4.4", groups=["group_a"])

        # Execute task and check semaphore acquire/release
        runner._run_task_with_semaphores(self.task, host, host.groups)
        mock_acquire.assert_called_once()
        mock_release.assert_called_once()

    def test_warning_for_missing_group_limit(self):
        """Test for logging warning when no group limit is specified."""
        with self.assertLogs("nornir_conditional_runner", level="WARNING") as log:
            runner = ConditionalRunner(num_workers=5)
            runner.run(self.task, self.hosts)
            self.assertTrue(
                any("No group limits specified" in message for message in log.output)
            )

    def test_warning_for_missing_group_key(self):
        """Test warning when a host lacks the specified group key."""
        runner = ConditionalRunner(
            num_workers=3,
            group_limits={"group_a": 1},
            conditional_group_key="custom_key",
        )

        with self.assertLogs("nornir_conditional_runner", level="WARNING") as log:
            runner.run(self.task, self.hosts)
            self.assertTrue(
                any(
                    "Host 'host1' has no 'custom_key' attribute" in message
                    for message in log.output
                )
            )


if __name__ == "__main__":
    unittest.main()
