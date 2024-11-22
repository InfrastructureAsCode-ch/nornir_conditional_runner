import time
import random
from datetime import datetime
from nornir import InitNornir
from nornir_rich.functions import print_result
from nornir.core.task import Task, Result
import logging

# Setting up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def run_task(task: Task, sleep_time: float) -> Result:
    """Runs a task that sleeps for a specified amount of time."""
    groups = task.host.get("groups", {})
    logger.info(f"Running on {task.host.hostname}; Device group: {groups}")
    time.sleep(sleep_time)
    logger.info(f"Done with {task.host.hostname}")
    
    return Result(
        task.host,
        result=f"My name is {task.host.hostname}! and I am in group {groups} and I ran for {sleep_time} seconds",
        # change this to do the demo for failed tasks
        failed=False #True if task.host.hostname == "core-02.example.com" else False,
    )

def hello_world_random(task: Task) -> Result:
    """Runs a task with random sleep time between 10 and 30 seconds."""
    runntime = random.uniform(10, 30)
    return run_task(task, runntime)

def hello_world(task: Task) -> Result:
    """Runs a task with a fixed sleep time of 20 seconds."""
    runntime = 20
    return run_task(task, runntime)

def init_nornir(runner_options: dict, inventory_options: dict) -> InitNornir:
    """Initializes and returns a Nornir object with the given options."""
    return InitNornir(
        runner=runner_options,
        inventory=inventory_options
    )

def demo1() -> None:
    """Demo1 - Running tasks with conditional groups and a fixed sleep time of 20 seconds."""
    runner_options = {
        "plugin": "ConditionalRunner",
        "options": {
            "num_workers": 100, # Number of workers
            # Group concurrent limits for each group
            "group_limits": {
                "core": 1,
                "edge": 3,
                "distribution": 1,
                "line1": 1,
                "line2": 1,
            },
            # Group fail limits for each group (optional)
            "group_fail_limits": {
                "core": 1,
                "edge": 1,
            },
            # Conditional group key to find groups in inventory > host.data
            "conditional_group_key": "conditional_groups",
        },
    }
    inventory_options = {
        "plugin": "SimpleInventory",
        "options": {
            "host_file": "demo/inventory/hosts.yaml",
            "group_file": "demo/inventory/groups.yaml",
        },
    }
    
    nr = init_nornir(runner_options, inventory_options)
    
    starttime = time.time()
    result = nr.run(hello_world)
    stoptime = time.time()
    print_result(result)
    logger.info(f"Time taken: {stoptime - starttime} seconds")

def demo2() -> None:
    """Demo2 - Running tasks with host groups and random sleep times."""
    runner_options = {
        "plugin": "ConditionalRunner",
        "options": {
            "num_workers": 100,
            "group_limits": {
                "critical_config": 1,
            },
        },
    }
    inventory_options = {
        "plugin": "SimpleInventory",
        "options": {
            "host_file": "demo/inventory/hosts.yaml",
            "group_file": "demo/inventory/groups.yaml",
        },
    }
    
    nr = init_nornir(runner_options, inventory_options)
    
    starttime = time.time()
    result_random = nr.run(hello_world_random)
    stoptime = time.time()
    print_result(result_random)
    logger.info(f"Time taken: {stoptime - starttime} seconds")

if __name__ == "__main__":
    demo1()
    demo2()
