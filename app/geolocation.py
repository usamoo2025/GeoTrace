import requests

def get_location(ip):
    try:
        response = requests.get(
            f"https://ipwho.is/{ip}",
            timeout=5
        )

        data = response.json()

        if not data.get("success"):
            return {}

        return {
            "country": data.get("country"),
            "city": data.get("city"),
            "region": data.get("region"),
            "isp": data.get("connection", {}).get("isp")
        }

    except requests.RequestException:
        return {}
