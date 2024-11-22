from nornir import InitNornir
from nornir_rich.functions import print_result
import time
import random
from datetime import datetime
from nornir.core.task import Task, Result


def hello_world_random(task: Task) -> Result:
    """Runing a task that sleeps for a random time between 10 and 30 seconds."""
    groups = task.host.get("groups", {})
    print(
        f"{datetime.now().time()}: Running on {task.host.hostname}; Device group: {groups}"
    )
    runntime = random.uniform(10, 30)
    time.sleep(runntime)
    print(f"{datetime.now().time()}: Done with {task.host.name}")
    return Result(
        task.host,
        result=f"My name is {task.host.hostname}! and I am in group {groups} and I ran for {runntime} seconds",
    )


def hello_world(task: Task) -> Result:
    """Runing a task that sleeps for 20 seconds."""
    conditional_groups = task.host.data.get("conditional_groups", task.host.groups)
    print(
        f"{datetime.now().time()}: Running on {task.host.hostname}; Device conditional_groups: {conditional_groups}"
    )
    runntime = 20
    time.sleep(runntime)
    print(f"{datetime.now().time()}: Done with {task.host.name}")
    return Result(
        task.host,
        result=f"My name is {task.host.hostname}! and I am in conditional_groups {conditional_groups} and I ran for {runntime} seconds", failed=True
    )


# Demo1 - Running tasks with conditional groups and a fixed sleep time of 20 seconds -> Expected to run in 40 seconds
nr = InitNornir(
    runner={
        "plugin": "ConditionalRunner",
        "options": {
            "num_workers": 100,
            "group_limits": {
                "core": 1,
                "edge": 3,
                "distribution": 1,
                "line1": 1,
                "line2": 1,
            },
            "group_fail_limits": {
                "core": 1,
                "edge": 1,
            },
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


starttime = time.time()
# Run the task using the custom runner
result = nr.run(hello_world)
stoptime = time.time()
print_result(result)
print(f"Time taken: {stoptime-starttime}")


# Demo2 - Running tasks with host groups and random sleep times (Warnig is expected for missing basic_config group limit)
starttime = time.time()
nr = InitNornir(
    runner={
        "plugin": "ConditionalRunner",
        "options": {
            "num_workers": 100,
            "group_limits": {
                # "basic_config": 100,
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

result_random = nr.run(hello_world_random)
stoptime = time.time()
print_result(result_random)
print(f"Time taken: {stoptime-starttime}")
