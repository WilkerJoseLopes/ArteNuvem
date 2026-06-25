import requests
import logging

logger = logging.getLogger(__name__)

def geocode_address(address_str):
    """
    Geocodes an address string using the OpenStreetMap Nominatim API.
    Returns a dictionary with latitude, longitude, city, country, and formatted_address,
    or None if the request fails or no results are found.
    """
    if not address_str or not address_str.strip():
        return None

    try:
        url = "https://nominatim.openstreetmap.org/search"
        params = {
            "q": address_str.strip(),
            "format": "json",
            "limit": 1,
            "addressdetails": 1
        }
        # OSM Nominatim requires a descriptive User-Agent header
        headers = {
            "User-Agent": "ArteNuvem-App/1.0 (academic project)"
        }
        
        response = requests.get(url, params=params, headers=headers, timeout=5)
        
        if response.status_code != 200:
            logger.error(f"OSM Nominatim Geocoding API returned status code {response.status_code}")
            return None
            
        results = response.json()
        if not results:
            logger.warning(f"No OSM geocoding results found for: '{address_str}'")
            return None
            
        first_result = results[0]
        lat = first_result.get("lat")
        lng = first_result.get("lon")
        
        if lat is None or lng is None:
            return None
            
        address_data = first_result.get("address", {})
        # OSM addresses can place city under city, town, village or municipality
        city = (
            address_data.get("city") or 
            address_data.get("town") or 
            address_data.get("village") or 
            address_data.get("municipality")
        )
        country = address_data.get("country")
        
        # Build clean address
        road = address_data.get("road")
        suburb = address_data.get("suburb")
        display_name = first_result.get("display_name", "")
        if road:
            formatted_address = f"{road}"
            if suburb:
                formatted_address += f", {suburb}"
        else:
            formatted_address = display_name.split(",")[0]
            
        return {
            "latitude": float(lat),
            "longitude": float(lng),
            "city": city,
            "country": country,
            "formatted_address": formatted_address
        }
        
    except requests.exceptions.RequestException as re:
        logger.error(f"Network error during OSM geocoding for '{address_str}': {re}")
        return None
    except Exception as e:
        logger.exception(f"Unexpected exception during OSM geocoding for '{address_str}': {e}")
        return None
