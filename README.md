# Nornir Conditional Runner

![Test Status](https://img.shields.io/github/actions/workflow/status/InfrastructureAsCode-ch/nornir_conditional_runner/main.yaml?label=Tests&style=flat-square)
![Coverage](https://img.shields.io/endpoint?url=https://InfrastructureAsCode-ch.github.io/nornir_conditional_runner/coverage-badge.json)
![PyPI](https://img.shields.io/pypi/v/nornir-conditional-runner?style=flat-square)
![PyPI - Downloads](https://img.shields.io/pypi/dm/nornir-conditional-runner?style=flat-square)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/nornir-conditional-runner?style=flat-square)
![GitHub](https://img.shields.io/github/license/InfrastructureAsCode-ch/nornir_conditional_runner?style=flat-square)



The `ConditionalRunner` is a custom Nornir runner that enforces concurrency limits based on host groups. It allows you to control task execution by defining limits on the number of simultaneous tasks for specific groups of hosts, ensuring your Nornir tasks do not update vital network devices simultaneously. You can also specify to skip the rest of the group if a certain number of vital tasks fail. It is built on the threaded runner, with added conditional `group_limits` and `group_fail_limits` managed internally by a data structure consisting of semaphores, conditions and counters, allowing tasks to remain idle in a waiting state until the start conditions are met.

## Installation

```bash
pip install nornir-conditional-runner
```

## Usage

Replace the default Nornir runner with `ConditionalRunner` in your configuration:

```python
from nornir import InitNornir

nr = InitNornir(
    runner={
        "plugin": "ConditionalRunner", # Add the ConditionalRunner plugin to your nornir config / config.yaml
        "options": {
            "num_workers": 10, # Maximum number of concurrent tasks
            "group_limits": {
                "core": 1, # Limit the "core" group to 1 concurrent task
                "distribution": 2,
                "edge": 3,
            },
            # Group fail limits for each group (optional) - once exceeded, the still waiting tasks are skipped
            "group_fail_limits": {
                "core": 1,  # Only allow one core device to fail
                "edge": 2,
            },
            "conditional_group_key": "conditional_groups", # Custom key for conditional groups config in host data
            "skip_unspecified_group_on_failure": True, # Sets the fail limit to 1 for all groups which do not have a group_fail_limit
    },
    inventory={
        "plugin": "SimpleInventory",
        "options": {
            "host_file": "demo/inventory/hosts.yaml",
            "group_file": "demo/inventory/groups.yaml",
        },
    },
)

def my_task(task):
    return f"Running on {task.host.name}"

result = nr.run(task=my_task)
print(result)
```
### Host Example
Hosts can define custom groups in their data dictionary using the `conditional_group_key` provided in the runner options. The runner will use these groups to enforce the `group_limits`.

```yaml
host1:
  data:
    conditional_groups:
      - core
host2:
  data:
    conditional_groups:
      - distribution
````

If the `conditional_group_key` is not provided, the runner will default to using the host groups.
```yaml
host1:
  groups: 
    - core
host2:
  groups: 
    - edge
```
### Fail Limits Feature
The `group_fail_limits` option allows you to specify the maximum number of failed tasks for a group before the runner skips the rest of the waiting tasks in a group. This feature is useful when you want to limit the impact of failing tasks on your network. By example, if one core device fails, you may want to skip the rest of the core devices to avoid further issues. The runner will only skip the tasks that are still waiting to run, not the ones that are already running.

The `skip_unspecified_group_on_failure` option sets the fail limit to 1 for all groups which do not have a `group_fail_limit` specified. This default behavior can be overridden by specifying `skip_unspecified_group_on_failure = False`, whitch will cause the runner to not skip the unspecified groups on failure. The specified `group_fail_limits` will allways be used to skip the group on failure.

## Logging

The ConditionalRunner leverages Python's built-in logging system to provide insights into its operation. It logs key events, such as:

- Warnings, when a group is configured on a host but it is missing in `group_limits`, defaulting to the global limit.
- Warnings, when an invalid or missing `conditional_group_key` causes a fallback to host groups.
- Warnings if the `group_fail_limits` for a group are met or exceeded.

## Demo

Three short demos can be found in the [demo/demo.py](demo/demo.py) file.

Demo topology with conditional groups:
![Demo topology](demo/demo_topology_drawio.png)

## Error Handling / fallback to default behavior of the threaded runner

- If the `conditional_group_key` is provided but no conditional groups are defined in the host data, the runner will warn you and default to using the host groups as the conditional groups.
- If no `group_limits` are specified for a group, the runner will default to using the global `num_workers` value as the limit.
- If neither `group_limits` nor a `conditional_group_key` are provided, the runner will fall back to using the host groups as conditional groups, with the default limits set to the global `num_workers`. -> This behavior then basically mirrors that of the default threaded Nornir runner.
- Invalid group limits (i.e., non-positive integers) will result in a ValueError.

## Contributing

Contributions are welcome! Feel free to submit issues or feature requests on GitHub.

--- 
Enjoy using the Nornir Conditional Runner! 🎉