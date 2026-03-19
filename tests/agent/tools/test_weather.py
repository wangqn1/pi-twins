"""Tests for the WeatherTool."""

from agent.tools.weather import WeatherTool, CITY_COORDINATES


class TestWeatherTool:
    """Test cases for WeatherTool."""

    def test_tool_attributes(self):
        """Test that tool has required attributes."""
        tool = WeatherTool()
        assert tool.name == "weather_query"
        assert tool.label == "Weather Query"
        assert "weather" in tool.description.lower()

    def test_missing_location_parameter(self):
        """Test error handling when location is missing."""
        tool = WeatherTool()
        result = tool.execute("test-id", {})
        assert result.content[0]["type"] == "text"
        assert "location" in result.content[0]["text"].lower()
        assert "required" in result.content[0]["text"].lower()

    def test_invalid_location(self):
        """Test error handling for invalid location."""
        tool = WeatherTool()
        result = tool.execute("test-id", {"location": "NonExistentCity12345"})
        assert result.content[0]["type"] == "text"
        assert "could not find location" in result.content[0]["text"].lower()

    def test_get_coordinates_from_fallback(self):
        """Test coordinate lookup from fallback dictionary."""
        tool = WeatherTool()
        
        # Test exact match
        coords = tool._get_coordinates("Beijing")
        assert coords == CITY_COORDINATES["beijing"]
        
        # Test case insensitivity
        coords = tool._get_coordinates("beijing")
        assert coords == CITY_COORDINATES["beijing"]
        
        # Test partial match
        coords = tool._get_coordinates("New York City")
        assert coords == CITY_COORDINATES["new york"]

    def test_fetch_weather_data(self):
        """Test fetching actual weather data."""
        tool = WeatherTool()
        result = tool.execute("test-id", {"location": "Beijing", "days": 3})
        
        assert result.content[0]["type"] == "text"
        assert "Weather forecast for Beijing" in result.content[0]["text"]
        assert "2026-03-16" in result.content[0]["text"]  # Current date
        assert "C /" in result.content[0]["text"]  # Temperature format

    def test_weather_details(self):
        """Test that details contain expected data."""
        tool = WeatherTool()
        result = tool.execute("test-id", {"location": "Tokyo", "days": 5})
        
        assert result.details is not None
        assert result.details["location"] == "Tokyo"
        assert "coordinates" in result.details
        assert "latitude" in result.details["coordinates"]
        assert "longitude" in result.details["coordinates"]
        assert result.details["forecast_days"] == 5
        assert "weather_data" in result.details

    def test_days_parameter_clamping(self):
        """Test that days parameter is clamped between 1 and 14."""
        tool = WeatherTool()
        
        # Test minimum
        result = tool.execute("test-id", {"location": "London", "days": 0})
        assert "1-Day Forecast" in result.content[0]["text"]
        
        # Test maximum
        result = tool.execute("test-id", {"location": "London", "days": 20})
        assert "14-Day Forecast" in result.content[0]["text"]

    def test_multiple_cities(self):
        """Test weather lookup for multiple supported cities."""
        tool = WeatherTool()
        cities = ["Shanghai", "Tokyo", "New York", "London", "Sydney"]
        
        for city in cities:
            result = tool.execute("test-id", {"location": city, "days": 2})
            assert result.content[0]["type"] == "text"
            assert city in result.content[0]["text"]


if __name__ == "__main__":
    test = TestWeatherTool()
    
    print('Running test_tool_attributes...')
    test.test_tool_attributes()
    print('PASS')

    print('Running test_missing_location_parameter...')
    test.test_missing_location_parameter()
    print('PASS')

    print('Running test_invalid_location...')
    test.test_invalid_location()
    print('PASS')

    print('Running test_get_coordinates_from_fallback...')
    test.test_get_coordinates_from_fallback()
    print('PASS')

    print('Running test_fetch_weather_data...')
    test.test_fetch_weather_data()
    print('PASS')

    print('Running test_weather_details...')
    test.test_weather_details()
    print('PASS')

    print('Running test_days_parameter_clamping...')
    test.test_days_parameter_clamping()
    print('PASS')

    print('Running test_multiple_cities...')
    test.test_multiple_cities()
    print('PASS')

    print()
    print('All tests passed!')
