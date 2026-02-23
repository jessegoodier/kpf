from rich.console import Console
from rich.table import Table

console = Console(width=60)
table = Table(title="Select a service", show_lines=False, expand=False, padding=(0, 1))
table.add_column("Name", header_style="bold white", style="bold white")
table.add_column("Ports", header_style="bold white", style="green", no_wrap=True)

table.add_row("short-svc", "80:80")
table.add_row(
    "some-very-long-service-name-that-is-important",
    "80:80, 443:443, 8080:8080, 9090:9090, 8081:8081, 8082:8082, 8083:8083",
)

console.print("Current behavior:")
console.print(table)

table2 = Table(title="Select a service", show_lines=False, expand=False, padding=(0, 1))
table2.add_column(
    "Name", header_style="bold white", style="bold white", overflow="ellipsis", no_wrap=True
)
table2.add_column(
    "Ports", header_style="bold white", style="green", ratio=1, overflow="ellipsis", no_wrap=True
)

table2.add_row("short-svc", "80:80")
table2.add_row(
    "some-very-long-service-name-that-is-important",
    "80:80, 443:443, 8080:8080, 9090:9090, 8081:8081, 8082:8082, 8083:8083",
)

console.print("With Ports ratio=1 and overflow='ellipsis':")
console.print(table2)

table3 = Table(title="Select a service", show_lines=False, expand=False, padding=(0, 1))
table3.add_column(
    "Name", header_style="bold white", style="bold white", overflow="ellipsis", no_wrap=True
)
table3.add_column(
    "Ports",
    header_style="bold white",
    style="green",
    overflow="ellipsis",
    no_wrap=True,
    max_width=30,
)

table3.add_row("short-svc", "80:80")
table3.add_row(
    "some-very-long-service-name-that-is-important",
    "80:80, 443:443, 8080:8080, 9090:9090, 8081:8081, 8082:8082, 8083:8083",
)

console.print("With max_width=30 on Ports and no_wrap=True on both:")
console.print(table3)
