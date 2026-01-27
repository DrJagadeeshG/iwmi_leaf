"""
LEAF DSS Configuration
Colors, thresholds, and intervention definitions
"""

# IWMI Brand Colors
COLORS = {
    "dark_blue": "#28537D",
    "light_blue": "#5088C6",
    "sky_blue": "#46BBD4",
    "teal": "#0297A6",
    "green": "#22AD7A",
    "orange": "#E86933",
    "yellow": "#DD9103",
    "light_grey": "#E8E7E7",
}

# Feasibility color scheme
FEASIBILITY_COLORS = {
    "very_high": "#1b5e20",
    "high": "#81c784",
    "moderate_high": "#c5e1a5",
    "moderate": "#ffd700",
    "low": "#ff8c00",
    "very_low": "#ff0000",
    "no_data": "#E0E0E0",
}

# Feasibility thresholds: (min, max, class_key, label)
FEASIBILITY_THRESHOLDS = [
    (100, 100, "very_high", "100%"),
    (75, 99.99, "high", "75-100%"),
    (50, 74.99, "moderate_high", "50-75%"),
    (25, 49.99, "moderate", "25-50%"),
    (1, 24.99, "low", "1-25%"),
    (0, 0.99, "very_low", "0%"),
]

# Variable groups
VARIABLE_GROUPS = {
    "land_agri": {
        "key": "land_agri",
        "name": "Land & Agriculture",
    },
    "water": {
        "key": "water",
        "name": "Water",
    },
    "infrastructure": {
        "key": "infrastructure",
        "name": "Infrastructure",
    },
    "livestock": {
        "key": "livestock",
        "name": "Livestock",
    },
    "people": {
        "key": "people",
        "name": "People & Collectives",
    },
    "soil": {
        "key": "soil",
        "name": "Soil",
    },
    "climate": {
        "key": "climate",
        "name": "Climate",
    },
}

# Map configuration
MAP_CONFIG = {
    "center": [22.5, 82.5],  # Center of India
    "zoom": 5,
    "tile_url": "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    "tile_attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
}
