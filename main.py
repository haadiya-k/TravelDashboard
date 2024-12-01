import streamlit as st
from datetime import datetime, timedelta
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
import plotly.express as px

# API Keys
GOOGLE_PLACES_API_KEY = st.secrets["google_key"]
TICKETMASTER_API_KEY = st.secrets["ticketmaster_key"]
OPENWEATHER_API_KEY = st.secrets["openweather_key"]
AMADEUS_CLIENT_ID = st.secrets["client_key"]
AMADEUS_CLIENT_SECRET = st.secrets["secret_key"]

# Load city list from CSV file
@st.cache_data
def load_city_data():
    return pd.read_csv("worldcities.csv")

cities_df = load_city_data()

# Weather icons and recommendations
weather_icons = {
    "clear sky": ("☀️", "Perfect day for outdoor events! Enjoy the sunshine."),
    "few clouds": ("🌤️", "Great weather for being outside! Slightly cloudy but enjoyable."),
    "scattered clouds": ("⛅", "Weather is suitable for events. Expect some clouds but mostly clear."),
    "overcast clouds": ("☁️", "Event-friendly, but keep an eye out for possible rain."),
    "rain": ("🌧️", "Not ideal for outdoor events. Consider indoor plans or prepare for rain."),
    "thunderstorm": ("⛈️", "Avoid outdoor events due to thunderstorms. Stay safe indoors."),
    "broken clouds": ("⛅", "Partly cloudy with some breaks of sunshine. Great for outdoor plans!")
}

# Function to retrieve Amadeus token
def get_amadeus_token():
    url = "https://test.api.amadeus.com/v1/security/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": AMADEUS_CLIENT_ID,
        "client_secret": AMADEUS_CLIENT_SECRET
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        st.write("Failed to retrieve Amadeus token:", response.json())
        return None

# Fetch events from Ticketmaster API with pagination
def get_all_events(city, start_date, end_date, categories):
    events = []
    url = "https://app.ticketmaster.com/discovery/v2/events.json"
    params = {
        'apikey': TICKETMASTER_API_KEY,
        'city': city,
        'startDateTime': start_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'endDateTime': end_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'size': 100,
    }
    for category in categories:
        params['classificationName'] = category
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            events.extend(data.get('_embedded', {}).get('events', []))
            page = data.get('page', {})
            while page['number'] < page['totalPages'] - 1:
                params['page'] = page['number'] + 1
                response = requests.get(url, params=params)
                if response.status_code != 200:
                    break
                data = response.json()
                events.extend(data.get('_embedded', {}).get('events', []))
                page = data.get('page', {})
        else:
            st.error("Could not retrieve events.")
            break
    events.sort(key=lambda x: x['dates']['start']['localDate'])
    return events

# Fetch weather data from OpenWeather API
def get_weather_data(city):
    forecast_url = f"http://api.openweathermap.org/data/2.5/forecast?q={city}&appid={OPENWEATHER_API_KEY}&units=metric"
    response = requests.get(forecast_url)
    if response.status_code == 200:
        return response.json()
    else:
        st.warning("Weather data could not be retrieved.")
        return None

# Function to get hotel data from Google Places API
def get_hotels(api_key, location, radius=5000):
    url = 'https://maps.googleapis.com/maps/api/place/nearbysearch/json'
    params = {
        'location': location,
        'radius': radius,
        'type': 'lodging',
        'key': api_key
    }
    response = requests.get(url, params=params)
    if response.status_code == 200:
        return response.json().get('results', [])
    else:
        st.error(f"Error fetching data from Google Places API: {response.status_code}")
        return []

# Function to search for flights using the retrieved token
def search_flights(token, origin, destination, departure_date, return_date, num_passengers, travel_class, trip_type,
                   max_stops):
    url = "https://test.api.amadeus.com/v2/shopping/flight-offers"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": num_passengers,
        "travelClass": travel_class,
        "currencyCode": "USD",
        "max": 249
    }
    if trip_type == "Round-Trip" and return_date:
        params["returnDate"] = return_date

    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            flights = data.get("data", [])
            dictionaries = data.get("dictionaries", {})  # Make sure to retrieve dictionaries

            filtered_flights = []
            for flight in flights:
                for itinerary in flight["itineraries"]:
                    segments = itinerary["segments"]
                    num_stops = len(segments) - 1
                    if max_stops == "All" or \
                            (max_stops == "Non-stop" and num_stops == 0) or \
                            (max_stops == "1 Stop" and num_stops == 1) or \
                            (max_stops == "2+ Stops" and num_stops >= 2):
                        filtered_flights.append(flight)
                        break
            return filtered_flights, data.get("dictionaries", {})
        else:
            st.write("Failed to retrieve flight data. Status code:", response.status_code)
            st.write("Response content:", response.text)
            return [], {}
    except requests.exceptions.JSONDecodeError:
        st.write("Failed to retrieve flight data. Non-JSON response received.")
        st.write("Response content:", response.text)
        return [], {}


# Function to format ISO 8601 duration
def format_duration(duration_str):
    hours, minutes = 0, 0
    if "H" in duration_str:
        hours = int(duration_str[2:].split("H")[0])
    if "M" in duration_str:
        minutes = int(duration_str.split("H")[-1].replace("M", ""))
    return f"{hours} hours {minutes} minutes"

def display_flights(flights, dictionaries):
    carriers = dictionaries.get("carriers", {})
    aircraft_types = dictionaries.get("aircraft", {})
    locations = dictionaries.get("locations", {})

    for i, flight in enumerate(flights, start=1):
        price = flight["price"]["grandTotal"]
        currency = flight["price"]["currency"]

        # Get the outbound flight details
        outbound_itinerary = flight["itineraries"][0]
        outbound_segments = outbound_itinerary["segments"]

        outbound_departure = outbound_segments[0]['departure']['iataCode']
        outbound_arrival = outbound_segments[-1]['arrival']['iataCode']
        outbound_route = f"{outbound_departure} - {outbound_arrival}"

        # If round-trip, get inbound flight details
        inbound_itinerary = None
        inbound_route = None
        if len(flight["itineraries"]) > 1:
            inbound_itinerary = flight["itineraries"][1]
            inbound_segments = inbound_itinerary["segments"]
            inbound_departure = inbound_segments[0]['departure']['iataCode']
            inbound_arrival = inbound_segments[-1]['arrival']['iataCode']
            inbound_route = f"{inbound_departure} - {inbound_arrival}"

        # Display the flight route and price
        st.write(f"### Flight {i}: {outbound_route} / {inbound_route}")
        st.write(f"**Price:** {currency} {price}")

        # Outbound Flight Section
        st.write("#### Outbound Flight")
        col1, col2 = st.columns(2)
        with col1:
            st.write(f"**Route:** {outbound_route}")
        with col2:
            display_itinerary(outbound_itinerary, carriers, aircraft_types, locations)

        # Inbound Flight Section
        if inbound_itinerary:
            st.write("#### Inbound Flight")
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Route:** {inbound_route}")
            with col2:
                display_itinerary(inbound_itinerary, carriers, aircraft_types, locations)

        # Divider between flights
        st.markdown("<hr>", unsafe_allow_html=True)


def display_itinerary(itinerary, carriers, aircraft_types, locations):
    total_duration = format_duration(itinerary["duration"])
    st.write(f"**Total Duration:** {total_duration}")

    for segment in itinerary["segments"]:
        # Extract segment details with fallbacks
        departure_info = segment["departure"]
        arrival_info = segment["arrival"]
        carrier_code = segment.get("carrierCode", "Unknown")
        flight_number = segment.get("number", "N/A")
        aircraft_code = segment.get("aircraft", {}).get("code", "Unknown")

        # Get details from dictionaries
        airline_name = carriers.get(carrier_code, "Unknown Airline")
        aircraft_name = aircraft_types.get(aircraft_code, "Unknown Aircraft")
        departure_airport = departure_info["iataCode"]
        arrival_airport = arrival_info["iataCode"]

        # Format times
        departure_time = datetime.fromisoformat(departure_info["at"]).strftime("%b %d, %Y - %I:%M %p")
        arrival_time = datetime.fromisoformat(arrival_info["at"]).strftime("%b %d, %Y - %I:%M %p")

        # Display details
        st.write(f"**Airline:** {airline_name} ({carrier_code}{flight_number})")
        st.write(f"**Aircraft:** {aircraft_name} ({aircraft_code})")
        st.write(f"**Route:** {departure_airport} - {arrival_airport}")
        st.write(f"**Departure:** {departure_time}")
        st.write(f"**Arrival:** {arrival_time}")
        st.write(f"**Flight Duration:** {format_duration(segment['duration'])}")
        st.write("---")


def plot_flight_prices(flights, dictionaries):
    # Create a list to hold the flight data with airlines and prices
    flight_data = []

    for flight in flights:
        price = float(flight["price"]["grandTotal"])  # Flight price in USD

        # Extract airline information
        airline_code = flight["itineraries"][0]["segments"][0]["carrierCode"]
        airline_name = dictionaries.get("carriers", {}).get(airline_code, "Unknown Airline")
        flight_data.append({"Airline": airline_name, "Price (USD)": price})

    # Convert the list to a pandas DataFrame
    df = pd.DataFrame(flight_data)

    # Calculate the mean price for each airline
    df_mean = df.groupby("Airline", as_index=False)["Price (USD)"].mean()

    # Plot the bar chart
    fig = px.bar(df_mean, x="Airline", y="Price (USD)", color="Airline",
                 title="Average Flight Prices by Airline",
                 labels={"Price (USD)": "Average Price in USD"})

    fig.update_layout(xaxis_title="Airline", yaxis_title="Average Price (USD)",
                      xaxis_tickangle=-45)

    st.plotly_chart(fig)  # Display the chart in Streamlit

def display_three_day_outlook(weather_data):
    st.write("### 3-Day Outlook")

    # Extract 3-Day Forecast Data
    three_day_forecast = []
    for item in weather_data["list"]:
        date_raw = datetime.strptime(item["dt_txt"], "%Y-%m-%d %H:%M:%S")
        day_of_week = date_raw.strftime("%A")  # Example: "Monday"
        date_formatted = date_raw.strftime("%B %d, %Y")  # Example: "November 18, 2024"
        temp_max = round(item["main"]["temp_max"])
        temp_min = round(item["main"]["temp_min"])
        precipitation = item.get("rain", {}).get("3h", 0)
        weather_desc = item["weather"][0]["description"].capitalize()
        weather_icon = weather_icons.get(weather_desc.lower(), ("🌤️", ""))[0]

        if not any(forecast["Date"] == date_formatted for forecast in three_day_forecast):
            three_day_forecast.append({
                "Day": day_of_week,
                "Date": date_formatted,
                "Max Temp": temp_max,
                "Min Temp": temp_min,
                "Rain": precipitation,
                "Weather": weather_desc,
                "Icon": weather_icon,
            })

        if len(three_day_forecast) == 3:  # Limit to 3 days
            break

    # Display Forecast in Three Columns
    col1, col2, col3 = st.columns(3)
    columns = [col1, col2, col3]

    for col, day in zip(columns, three_day_forecast):
        with col:
            st.markdown(
                f"""
                <div style="
                    border: 1px solid #d3d3d3; 
                    padding: 10px; 
                    margin-bottom: 10px; 
                    border-radius: 5px; 
                    text-align: center; 
                    height: 220px;  /* Set a fixed height */
                    display: flex; 
                    flex-direction: column; 
                    justify-content: space-between;
                ">
                <h4 style="margin: 0; font-size: 18px; color: #333;">{day['Day']}</h4>
                <h5 style="margin: 0; font-size: 16px; color: #666;">{day['Date']}</h5>
                <p style="margin: 4px 0; font-size: 14px;"><b>Max:</b> {day['Max Temp']}°C</p>
                <p style="margin: 4px 0; font-size: 14px;"><b>Min:</b> {day['Min Temp']}°C</p>
                <p style="margin: 4px 0; font-size: 14px;"><b>Rain:</b> {day['Rain']} mm</p>
                <p style="margin: 4px 0; font-size: 14px;"><b>Weather:</b> {day['Weather']} {day['Icon']}</p>
                </div>
                """,
                unsafe_allow_html=True
            )

def display_forecast_line_graph(weather_data):
    st.write("### Weather Forecast (Next 24 Hours)")

    # Prepare data for the next 24 hours
    hourly_forecast = []
    current_time = datetime.now()

    for item in weather_data["list"]:
        datetime_str = item["dt_txt"]
        datetime_obj = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")

        # Filter to include only the next 24 hours
        if current_time <= datetime_obj <= current_time + timedelta(hours=24):
            formatted_time = datetime_obj.strftime("%I %p")  # Example: "9 PM"
            temp = round(item["main"]["temp"])
            rain = item.get("rain", {}).get("3h", 0)
            wind_speed_kmh = round(item["wind"]["speed"] * 3.6, 1)  # Convert m/s to km/h

            hourly_forecast.append({
                "Time": formatted_time,
                "Temperature (°C)": temp,
                "Rain (mm)": rain,
                "Wind Speed (km/h)": wind_speed_kmh,
            })

    # Convert to DataFrame for visualization
    df_forecast = pd.DataFrame(hourly_forecast)

    # Check if data is available for the next 24 hours
    if not df_forecast.empty:
        # Plot line graph for temperature, rain, and wind speed
        fig = px.line(
            df_forecast.melt(id_vars="Time"),  # Melt to plot multiple metrics
            x="Time", y="value", color="variable",
            title="Forecast Trends (Next 24 Hours)",
            labels={"Time": "Time", "value": "Value", "variable": "Metric"}
        )
        fig.update_layout(xaxis_title="Time", yaxis_title="Forecast Values")
        st.plotly_chart(fig)
    else:
        st.warning("No data available for the next 24 hours.")


# Function for Long-Term Outlook
def display_long_term_outlook(weather_data):
    st.write("### Extended Weather Outlook (Up 5 days)")

    # Extract extended forecast data
    long_term_forecast = []
    for item in weather_data["list"]:
        date = item["dt_txt"].split(" ")[0]  # Extract the date part
        temp_max = round(item["main"]["temp_max"])
        temp_min = round(item["main"]["temp_min"])
        rain = round(item.get("rain", {}).get("3h", 0), 1)  # Rainfall in mm
        wind_speed = round(item["wind"]["speed"], 1)
        humidity = item["main"]["humidity"]  # Humidity as percentage
        weather_desc = item["weather"][0]["description"].capitalize()

        # Avoid duplicate entries for the same date
        if not any(forecast["Date"] == date for forecast in long_term_forecast):
            long_term_forecast.append({
                "Date": date,
                "Max Temp (°C)": temp_max,
                "Min Temp (°C)": temp_min,
                "Rain (mm)": rain,
                "Wind Speed (m/s)": wind_speed,
                "Humidity (%)": humidity,
                "Weather": weather_desc,
            })

        # Break after two weeks (14 days) if desired
        if len(long_term_forecast) == 14:  # Extend to 30 for a month if data permits
            break

    # Convert the forecast data to a pandas DataFrame
    df_long_term = pd.DataFrame(long_term_forecast)

    # Display the interactive table with travel-relevant components
    st.dataframe(df_long_term, use_container_width=True)

# Sidebar Navigation
st.sidebar.title("🌐 Travel Dashboard")
st.sidebar.markdown("Plan and explore events, weather, hotels, and flights for your destination!")

# Updated Sidebar Options with emojis and more user-friendly labels
page = st.sidebar.radio(
    "Navigate to:",
    [
        "🏠 Home - Overview",
        "✈️ Flights - Book Your Travel",
        "🏨 Hotels - Find Accommodations",
        "🎉 Events - Find Local Happenings",
        "🌦️ Weather Forecast - Check Weather"
    ]
)

if page == "🏠 Home - Overview":
    st.title("Welcome to the Travel Dashboard!")
    st.markdown("""
        This dashboard allows you to explore various travel-related information for your chosen destination, including:
        - Flight options for your travel needs
        - Available hotels and accommodations
        - Events in the selected city
        - Local weather forecasts
    """)

# Flights
elif page == "✈️ Flights - Book Your Travel":
    st.subheader("Flight Search")
    origin = st.text_input("Departure Airport Code", "JFK")
    destination = st.text_input("Destination Airport Code", "LAX")
    trip_type = st.radio("Trip Type", ["One-Way", "Round-Trip"], key="trip_type")
    departure_date = st.date_input("Departure Date")
    return_date = st.date_input("Return Date") if trip_type == "Round-Trip" else None

    if trip_type == "Round-Trip" and return_date < departure_date:
        st.error("Return date cannot be before the departure date. Please select a valid return date.")

    travel_class = st.selectbox("Travel Class", ["ECONOMY", "BUSINESS", "FIRST"])
    num_passengers = st.number_input("Number of Passengers", min_value=1, max_value=10, value=1)
    max_stops = st.selectbox("Number of Stops", ["All", "Non-stop", "1 Stop", "2+ Stops"], index=0)

    if st.button("Search Flights"):
        with st.spinner("Searching for flights..."):
            token = get_amadeus_token()
            if token:
                flights, dictionaries = search_flights(token, origin, destination, departure_date, return_date, num_passengers, travel_class, trip_type, max_stops)
                if flights:
                    st.write("### Flight Results")
                    plot_flight_prices(flights,dictionaries)
                    display_flights(flights, dictionaries)
                else:
                    st.warning("No flights found for the selected route.")
            else:
                st.warning("Authorization failed. Please check your API credentials.")

# Hotels Page with Tabs for Search and Map
elif page == "🏨 Hotels - Find Accommodations":
    st.title("🏨 Hotels - Find Accommodations")

    # Create tabs for hotel search and map view
    tab1, tab2 = st.tabs(["Search Hotels", "Map View"])

    # Tab 1: Hotel Search
    with tab1:
        st.subheader("Search Hotels")

        # Input fields for city, start date, and end date on the Search Hotels tab
        city = st.selectbox("Select a City:", cities_df["city"].unique())
        start_date = st.date_input("Start Date", datetime.now())
        end_date = st.date_input("End Date", datetime.now() + timedelta(days=3))

        # Check that the end date is not before the start date
        if end_date < start_date:
            st.error("End date cannot be before start date.")
        else:
            city_data = cities_df[cities_df["city"] == city].iloc[0]
            location = f"{city_data['lat']},{city_data['lng']}"

            # Search button
            if st.button("Search Hotels"):
                with st.spinner(f"Searching for hotels in {city}..."):
                    hotels = get_hotels(GOOGLE_PLACES_API_KEY, location)

                    if hotels:
                        for hotel in hotels:
                            st.write(f"**{hotel['name']}**")
                            st.write(f"Rating: {hotel.get('rating', 'N/A')} | Address: {hotel.get('vicinity', 'N/A')}")
                            if 'photos' in hotel:
                                photo_reference = hotel['photos'][0]['photo_reference']
                                st.image(
                                f"https://maps.googleapis.com/maps/api/place/photo?maxwidth=400&photoreference={photo_reference}&key={GOOGLE_PLACES_API_KEY}")
                            st.markdown("---")
                    else:
                        st.warning("No hotels found for the selected dates and location.")

    # Tab 2: Map View
    with tab2:
        st.subheader("Hotel Map")
        hotel_map = folium.Map(location=[float(city_data["lat"]), float(city_data["lng"])], zoom_start=12)

        # Plot each hotel on the map if search has been conducted
        if 'hotels' in locals() and hotels:
            for hotel in hotels:
                lat = hotel['geometry']['location']['lat']
                lng = hotel['geometry']['location']['lng']
                hotel_name = hotel['name']
                folium.Marker(
                    [lat, lng],
                    popup=f"{hotel_name}<br>Rating: {hotel.get('rating', 'N/A')}",
                    tooltip=hotel_name
                ).add_to(hotel_map)
            folium_static(hotel_map, width=700, height=500)
        else:
            st.write("No hotels found to display on the map.")

# Event Page
elif page == "🎉 Events - Find Local Happenings":
    st.title("🎉 Events - Find Local Happenings")

    # Create tabs for event search/details and map view
    tab1, tab2 = st.tabs(["Search & Details", "Event Map"])

    # Tab 1: Event Search & Details
    with tab1:
        st.subheader("Search for Events")

        city = st.selectbox("Select a City for Events:", cities_df["city"].unique(), key="events_city")
        start_date = st.date_input("Event Start Date", datetime.now(), key="event_start_date")
        end_date = st.date_input("Event End Date", datetime.now() + timedelta(days=7), key="event_end_date")

        if start_date > end_date:
            st.error("Start date cannot be after end date. Please select a valid start date.")

        st.write("Choose event categories you are interested in:")
        selected_categories = [
            category for category, label in zip(
                ["Music", "Sports", "Arts & Theatre", "Comedy", "Festivals"],
                ["🎶 Music", "🏅 Sports", "🎭 Arts & Theatre", "😂 Comedy", "🎉 Festivals"]
            ) if st.checkbox(label)
        ]

        if st.button("Search Events"):
            with st.spinner(f"Searching for events in {city}..."):
                if selected_categories:
                    events = get_all_events(city, start_date, end_date, selected_categories)
                    st.session_state.events_data = events

                    # Fetch weather data for the selected city
                    weather_data = get_weather_data(city)
                    daily_forecast = {}

                    if weather_data:
                        # Process weather data into daily forecast
                        for item in weather_data['list']:
                            date_str, temp, weather = item['dt_txt'].split(" ")[0], round(item['main']['temp']), \
                            item['weather'][0]['description']
                            if date_str not in daily_forecast:
                                daily_forecast[date_str] = {
                                    'high': temp,
                                    'low': temp,
                                    'weather': weather,
                                    'icon': weather_icons.get(weather, "🌥️")[0],
                                    'recommendation': weather_icons.get(weather, ("🌥️", "Check weather details"))[1]
                                }
                            else:
                                daily_forecast[date_str]['high'] = max(daily_forecast[date_str]['high'], temp)
                                daily_forecast[date_str]['low'] = min(daily_forecast[date_str]['low'], temp)

                    if events:
                        for event in events:
                            event_name = event.get('name', 'N/A')
                            event_date = event.get('dates', {}).get('start', {}).get('localDate', 'N/A')
                            venue = event.get('_embedded', {}).get('venues', [{}])[0]
                            venue_name = venue.get('name', 'N/A')
                            venue_address = venue.get('address', {}).get('line1',
                                                                     'Address not available')  # Extract address
                            event_url = event.get('url', '#')
                            event_image = event.get('images', [{}])[0].get('url', None)

                            # Get the weather forecast for the event's date
                            weather_info = daily_forecast.get(event_date, {})
                            weather_icon = weather_info.get('icon', "🌥️")
                            recommendation = weather_info.get('recommendation', "Check weather details")

                            # Display event details with weather recommendations
                            col1, col2 = st.columns([1, 2])
                            with col1:
                                if event_image:
                                    st.image(event_image, use_container_width=True, caption=event_name)
                                else:
                                    st.write("No image available")

                            with col2:
                                st.subheader(event_name)
                                st.write(f"**Date:** {event_date}")
                                st.write(f"**Venue:** {venue_name}")
                                st.write(f"**Address:** {venue_address}")  # Show address
                                st.write(f"[More Details]({event_url})")
                                st.write(f"**Weather:** {weather_icon} {recommendation}")
                            st.markdown("---")
                    else:
                        st.warning("No events found for the selected criteria.")
                else:
                    st.warning("Please select at least one event category.")

    # Tab 2: Event Map
    with tab2:
        st.subheader("Event Map")
        if 'events_data' in st.session_state and st.session_state.events_data:
            city_data = cities_df[cities_df["city"] == city].iloc[0]
            event_map = folium.Map(location=[float(city_data["lat"]), float(city_data["lng"])], zoom_start=12)

            for event in st.session_state.events_data:
                venue = event.get('_embedded', {}).get('venues', [{}])[0]
                venue_lat = venue.get('location', {}).get('latitude')
                venue_lon = venue.get('location', {}).get('longitude')
                venue_address = venue.get('address', {}).get('line1', 'Address not available')  # Address extraction
                event_name = event.get('name', 'Event')
                event_date = event.get('dates', {}).get('start', {}).get('localDate', 'N/A')

                if venue_lat and venue_lon:
                    popup_content = f"""
                        {event_name}<br>
                        Date: {event_date}<br>
                        Address: {venue_address}
                    """
                    folium.Marker([float(venue_lat), float(venue_lon)], popup=popup_content).add_to(event_map)

            folium_static(event_map, width=700, height=500)
        else:
            st.write("No events found. Please search for events in the 'Search & Details' tab.")

# Weather Forecast
elif page == "🌦️ Weather Forecast - Check Weather":
    # Initialize session state for city selection
    if "selected_city" not in st.session_state:
        st.session_state.selected_city = cities_df["city"].iloc[0]  # Default to the first city

    # Prefill city selection with session state
    st.session_state.selected_city = st.selectbox("Select a City:", cities_df["city"].unique(), index=cities_df["city"].tolist().index(st.session_state.selected_city))

    weather_data = get_weather_data(st.session_state.selected_city)
    if weather_data:
        st.subheader(f"Weather Forecast for {st.session_state.selected_city}")

        # Display 3-Day Outlook
        display_three_day_outlook(weather_data)

        # Display Hourly Forecast
        display_forecast_line_graph(weather_data)

        # Display Long-Term Outlook
        display_long_term_outlook(weather_data)
