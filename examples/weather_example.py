#!/usr/bin/env python3
"""Example usage of the WeatherTool."""

import sys
sys.path.insert(0, 'src')

from agent.tools.weather import WeatherTool


def main():
    """Demonstrate weather tool usage."""
    tool = WeatherTool()
    
    print("=" * 60)
    print("Weather Query Tool Example")
    print("=" * 60)
    print()
    
    # Example 1: Query Beijing weather
    print("Querying weather for Beijing...")
    result = tool.execute("example-1", {"location": "Beijing", "days": 5})
    print(result.content[0]["text"])
    print()
    
    # Example 2: Query multiple cities
    cities = ["Tokyo", "New York", "London"]
    print(f"Querying weather for {', '.join(cities)}...")
    print()
    
    for city in cities:
        result = tool.execute("example-2", {"location": city, "days": 3})
        # Print first few lines only
        lines = result.content[0]["text"].split("\n")
        for line in lines[:4]:
            print(line)
        print("...")
        print()
    
    # Example 3: Error handling
    print("Testing error handling with invalid location...")
    result = tool.execute("example-3", {"location": "NonExistentCity123"})
    print(result.content[0]["text"])
    print()
    
    print("=" * 60)
    print("Example completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
