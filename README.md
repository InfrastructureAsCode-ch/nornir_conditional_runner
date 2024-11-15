# Nornir Conditional Runner

The `ConditionalRunner` is a custom Nornir runner that enforces concurrency limits based on host groups or custom condition groups. It allows you to control task execution by defining limits on the number of simultaneous tasks for specific groups of hosts, ensuring your nornir tasks are not updating vital network devices at the same time.

## Installation

```bash
pip install nornir-conditional-runner
```

## Usage

Replace the default Nornir runner with `ConditionalRunner` in your configuration:

```python
from nornir import InitNornir
from conditional_runner import ConditionalRunner

nr = InitNornir(
    runner={
        "plugin": "conditional_runner", # Use the ConditionalRunner instead of the default
        "options": {
            "num_workers": 10, # Maximum number of concurrent tasks
            "group_limits": {
                "core": 1, # Limit the "core" group to 1 concurrent task
                "distribution": 2,
                "edge": 3,
            },
            "conditional_group_key": "conditional_groups", # Custom key for conditional groups config in host data
        },
    },
    inventory={
        "plugin": "SimpleInventory",
        "options": {
            "host_file": "inventory/hosts.yaml",
            "group_file": "inventory/groups.yaml",
        },
    },
)

def my_task(task):
    return f"Running on {task.host.name}"

result = nr.run(task=my_task)
print(result)
```
### Host Example
Hosts can define custom groups in their data dictionary using the `conditional_group_key` provided to the runner. The runner will use these groups to enforce the `group_limits`.

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
If no conditional groups are defined and `conditional_group_key` is not provided to the runner, the runner will use the host groups.

```yaml
host1:
  groups: 
    - core
host2:
  groups: 
    - edge
```
## Logging

The ConditionalRunner leverages Python's built-in logging system to provide insights into its operation. It logs key events, such as:

- Warnings when a group limit is missing in group_limits, defaulting to the global limit.
- Warnings when an invalid or missing conditional_group_key causes a fallback to host groups.

## Demo

A demo can be found in the [demo/demo.py](demo/demo.py) file.

Demo topology with conditional groups:
![Demo topology](demo/demo_topology.drawio.png)

## Error Handling

If no group_limits are specified for a group, the runner will default to using the global num_workers value as the limit.

Invalid group limits (i.e., non-positive integers) will result in a ValueError.

If neither group_limits nor a conditional_group_key are provided, the runner will fall back to using the host groups as conditional groups, with the default limits set to the global num_workers. This behavior thean basically mirrors that of the default threaded Nornir runner.

## Contributing

Contributions are welcome! Feel free to submit issues or feature requests on GitHub.

--- 
Enjoy using the Nornir Conditional Runner! 🎉