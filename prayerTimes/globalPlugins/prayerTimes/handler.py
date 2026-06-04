from datetime import datetime
import requests
# a function for Detecting current location
def detectLocation():
    try:
        baseURL="http://ip-api.com/json/"
        response=requests.get(baseURL)
        if response.status_code!=200:
            raise Exception("An error detected")
        data=response.json()
        if data["status"]!="success":
            raise Exception("An error detected")
        lat=data["lat"]
        lon=data["lon"]
        return lat,lon
    except:
        raise Exception("An error detected")
# A function for getting current prayer times
def getCurrentPrayerTimes(latitude:float,longitude:float):
    method = 5
    response = requests.get('http://api.aladhan.com/v1/timings', params={
        'latitude': latitude,
        'longitude': longitude,
        'method': method
    })
    if response.status_code == 200:
        data = response.json()['data']['timings']
        prayers_ar = {
            'Fajr': _('Fajr'),
            'Sunrise': _('Sunrise'),
            'Dhuhr': _('Dhuhr'),
            'Asr': _('Asr'),
            'Maghrib': _('Maghrib'),
            'Isha': _('Isha')
        }
        prayers = list(prayers_ar.values())
        times = []
        for prayer_en, prayer_ar in prayers_ar.items():
            time_24h = data[prayer_en]
            time_12h = datetime.strptime(time_24h, "%H:%M").strftime("%I:%M %p")
            times.append(f"{prayer_ar}: {time_12h}")
    else:
        raise Exception("An error detected")
    return "\n".join(times)
