import time
import random
from datetime import datetime
from nornir import InitNornir
from nornir_rich.functions import print_result
from nornir.core.task import Task, Result
from typing import List


def run_task(task: Task, sleep_time: float, groups: List[str]) -> Result:
    """Run a task that sleeps for a specified amount of time."""
    print(
        f"{datetime.now().time()}: Running on {task.host.hostname}; Device group: {groups}"
    )
    time.sleep(sleep_time)
    print(f"{datetime.now().time()}: Done with {task.host.hostname}")

    return Result(
        task.host,
        result=f"My name is {task.host.hostname}! and I am in group {groups} and I ran for {sleep_time} seconds",
        failed=True if task.host.data.get("fail", False) else False,
    )


def hello_world_random(task: Task) -> Result:
    """Runing a task that sleeps for a random time between 5 and 20 seconds."""
    groups = task.host.get("groups", {})
    return run_task(task, random.randint(5, 20), groups)


def hello_world(task: Task) -> Result:
    """Runing a task that sleeps for 15 seconds."""
    conditional_groups = task.host.data.get("conditional_groups", task.host.groups)
    return run_task(task, 15, conditional_groups)


def demo1(failed_tasks: bool = False) -> None:
    """Demo1 - Running tasks with conditional groups and a fixed sleep time of 15 seconds."""
    print(
        f"\n\n ---- Demo1 {'with failed hosts and fail limits' if failed_tasks else ''} ---- \n"
    )

    nr = InitNornir(
        runner={
            "plugin": "ConditionalRunner",
            "options": {
                "num_workers": 100,  # Number of workers
                # Group concurrent limits for each group
                "group_limits": {
                    "core": 1,  # Just update one core at a time
                    "edge": 3,  # Update 3 edge devices at a time
                    "distribution": 1,
                    "line1": 1,
                    "line2": 1,
                },
                # Group fail limits for each group (optional) - once exceeded, the still waiting tasks are skipped
                "group_fail_limits": {
                    "core": 1,  # Only allow one core device to fail
                    "edge": 3,
                },
                "skip_group_on_failure": True,  # Default: True -> skips the rest of the group if a device fails (can be deactivated here)
                # Conditional group key so you can configure the condition groups in inventory > host.data
                "conditional_group_key": "conditional_groups",
            },
        },
        inventory={
            "plugin": "SimpleInventory",
            "options": {
                "host_file": "demo/inventory/hosts.yaml",
                "group_file": "demo/inventory/groups.yaml",
            },
        },
    )
    if failed_tasks:
        nr.inventory.hosts["core-02"].data["fail"] = True
        nr.inventory.hosts["edge-01"].data["fail"] = True
        nr.inventory.hosts["edge-02"].data["fail"] = True
    starttime = time.time()
    result = nr.run(hello_world)
    stoptime = time.time()
    print_result(result)
    print(f"Time taken: {stoptime - starttime} seconds")


def demo2() -> None:
    """Demo2 - Running tasks with host groups and random sleep times and minimal options."""
    print("\n\n ---- Demo2 ---- \n")
    nr = InitNornir(
        runner={
            "plugin": "ConditionalRunner",
            "options": {
                "num_workers": 100,
                "group_limits": {
                    "critical_config": 1,
                },
            },
        },
        inventory={
            "plugin": "SimpleInventory",
            "options": {
                "host_file": "demo/inventory/hosts.yaml",
                "group_file": "demo/inventory/groups.yaml",
            },
        },
    )

    starttime = time.time()
    result_random = nr.run(hello_world_random)
    stoptime = time.time()
    print_result(result_random)
    print(f"Time taken: {stoptime - starttime} seconds")


if __name__ == "__main__":
    demo1(failed_tasks=False)
    demo2()
    demo1(failed_tasks=True) # This will fail core-02 and edge-01 and edge-02 -> core-02 will cause the group core and link2 (skip_group_on_failure = True) to be skipped.
