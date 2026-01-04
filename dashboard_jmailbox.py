import streamlit as st
import paho.mqtt.client as mqtt
import json
import time
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import threading
import queue
import sys

# ==================== KONFIGURASI HALAMAN ====================
st.set_page_config(
    page_title="J-MAILBOX Dashboard",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== KONFIGURASI MQTT ====================
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPICS = [
    "jmailbox/+/status",      # Status perangkat
    "jmailbox/+/sensor",      # Data sensor
    "jmailbox/+/alert",       # Alert keamanan
    "jmailbox/+/log",         # Log sistem
    "jmailbox/+/camera",      # Perintah kamera
    "jmailbox/+/payment",     # Status pembayaran
]

# ==================== INISIALISASI STATE ====================
if 'mqtt_client' not in st.session_state:
    st.session_state.mqtt_client = None
    st.session_state.mqtt_connected = False

if 'devices' not in st.session_state:
    st.session_state.devices = {}

if 'system_logs' not in st.session_state:
    st.session_state.system_logs = []

if 'security_alerts' not in st.session_state:
    st.session_state.security_alerts = []

if 'sensor_data' not in st.session_state:
    st.session_state.sensor_data = {
        'distance': [],
        'timestamp': [],
        'wifi_rssi': []
    }

if 'current_package' not in st.session_state:
    st.session_state.current_package = {
        'resi': None,
        'status': 'No active delivery',
        'timestamp': None,
        'is_cod': False,
        'amount': 0
    }

# Queue untuk komunikasi antar-thread
message_queue = queue.Queue()

# ==================== FUNGSI MQTT ====================
def on_connect(client, userdata, flags, rc):
    """Callback ketika terkoneksi ke broker MQTT"""
    if rc == 0:
        st.session_state.mqtt_connected = True
        # Subscribe ke semua topik
        for topic in MQTT_TOPICS:
            client.subscribe(topic, qos=1)
        message_queue.put(("INFO", "Connected to MQTT Broker"))
    else:
        message_queue.put(("ERROR", f"Connection failed with code {rc}"))

def on_message(client, userdata, msg):
    """Callback ketika menerima pesan MQTT"""
    try:
        payload = msg.payload.decode()
        data = json.loads(payload)
        topic = msg.topic
        
        # Masukkan pesan ke queue untuk diproses di thread utama
        message_queue.put(("DATA", {
            "topic": topic,
            "data": data,
            "timestamp": datetime.now()
        }))
    except Exception as e:
        message_queue.put(("ERROR", f"Error processing MQTT message: {str(e)}"))

def process_mqtt_messages():
    """Proses pesan dari queue MQTT"""
    while not message_queue.empty():
        msg_type, content = message_queue.get_nowait()
        
        if msg_type == "INFO" or msg_type == "ERROR":
            # Tambahkan ke log
            st.session_state.system_logs.append({
                "timestamp": datetime.now(),
                "level": msg_type,
                "message": content,
                "device": "Dashboard"
            })
            
        elif msg_type == "DATA":
            topic = content["topic"]
            data = content["data"]
            timestamp = content["timestamp"]
            
            # Ekstrak device ID dari topic
            parts = topic.split('/')
            if len(parts) >= 2:
                device_id = parts[1]
                
                # Update device info
                if device_id not in st.session_state.devices:
                    st.session_state.devices[device_id] = {
                        'id': device_id,
                        'type': 'ESP32-CAM' if 'cam' in device_id else 'ESP32',
                        'last_seen': timestamp,
                        'status': {}
                    }
                
                st.session_state.devices[device_id]['last_seen'] = timestamp
                st.session_state.devices[device_id]['status'].update(data)
                
                # Proses berdasarkan tipe data
                if 'sensor' in topic:
                    # Simpan data sensor
                    if 'distance' in data:
                        st.session_state.sensor_data['distance'].append({
                            'value': data['distance'],
                            'timestamp': timestamp
                        })
                    if 'wifi_rssi' in data:
                        st.session_state.sensor_data['wifi_rssi'].append({
                            'value': data['wifi_rssi'],
                            'timestamp': timestamp
                        })
                    
                    # Simpan hanya 100 data terbaru
                    for key in st.session_state.sensor_data:
                        if len(st.session_state.sensor_data[key]) > 100:
                            st.session_state.sensor_data[key] = st.session_state.sensor_data[key][-100:]
                
                elif 'alert' in topic:
                    # Tambahkan alert keamanan
                    st.session_state.security_alerts.append({
                        "timestamp": timestamp,
                        "device": device_id,
                        "reason": data.get('reason', 'Unknown'),
                        "severity": data.get('severity', 1),
                        "message": data.get('message', '')
                    })
                
                elif 'log' in topic:
                    # Tambahkan log sistem
                    st.session_state.system_logs.append({
                        "timestamp": timestamp,
                        "level": data.get('level', 'INFO'),
                        "message": data.get('message', ''),
                        "device": device_id
                    })
                
                elif 'status' in topic:
                    # Update status paket jika ada
                    if 'resi' in data and data['resi']:
                        st.session_state.current_package['resi'] = data['resi']
                        st.session_state.current_package['status'] = data.get('status', 'In Progress')
                        st.session_state.current_package['timestamp'] = timestamp
                        st.session_state.current_package['is_cod'] = data.get('is_cod', False)
                        st.session_state.current_package['amount'] = data.get('amount', 0)

def init_mqtt():
    """Inisialisasi koneksi MQTT"""
    if st.session_state.mqtt_client is None or not st.session_state.mqtt_connected:
        try:
            client = mqtt.Client(client_id=f"dashboard_{int(time.time())}")
            client.on_connect = on_connect
            client.on_message = on_message
            
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.loop_start()
            
            st.session_state.mqtt_client = client
            time.sleep(1)  # Beri waktu untuk koneksi
            return True
        except Exception as e:
            st.error(f"Failed to connect to MQTT: {str(e)}")
            return False
    return True

def send_command(device_id, command, data=None):
    """Kirim perintah ke device via MQTT"""
    if st.session_state.mqtt_client and st.session_state.mqtt_connected:
        topic = f"jmailbox/{device_id}/command"
        payload = {
            "command": command,
            "timestamp": int(time.time() * 1000),
            "source": "dashboard"
        }
        if data:
            payload.update(data)
        
        try:
            st.session_state.mqtt_client.publish(topic, json.dumps(payload), qos=1)
            
            # Log perintah yang dikirim
            st.session_state.system_logs.append({
                "timestamp": datetime.now(),
                "level": "INFO",
                "message": f"Sent command '{command}' to {device_id}",
                "device": "Dashboard"
            })
            return True
        except Exception as e:
            st.session_state.system_logs.append({
                "timestamp": datetime.now(),
                "level": "ERROR",
                "message": f"Failed to send command: {str(e)}",
                "device": "Dashboard"
            })
            return False
    return False

# ==================== FUNGSI TAMPILAN ====================
def render_sidebar():
    """Render sidebar dengan device list dan kontrol cepat"""
    with st.sidebar:
        st.title("📦 J-MAILBOX")
        st.markdown("---")
        
        # Status koneksi
        col1, col2 = st.columns(2)
        with col1:
            if st.button("🔗 Connect", use_container_width=True):
                if init_mqtt():
                    st.success("Connected!")
                else:
                    st.error("Connection failed")
        with col2:
            if st.button("🔄 Refresh", use_container_width=True):
                st.rerun()
        
        st.markdown("### 🌐 Connected Devices")
        
        # Device list
        device_list = list(st.session_state.devices.keys())
        if not device_list:
            st.info("No devices connected")
            selected_device = None
        else:
            selected_device = st.selectbox(
                "Select Device",
                options=device_list,
                format_func=lambda x: f"{x} ({st.session_state.devices[x]['type']})"
            )
        
        st.markdown("---")
        st.markdown("### ⚡ Quick Commands")
        
        # Tombol kontrol cepat
        if selected_device:
            col1, col2 = st.columns(2)
            with col1:
                if st.button("📦 Start Delivery", use_container_width=True):
                    send_command(selected_device, "start_delivery")
            with col2:
                if st.button("📡 Status", use_container_width=True):
                    send_command(selected_device, "system_status")
            
            col3, col4 = st.columns(2)
            with col3:
                if st.button("🚪 Open", use_container_width=True, type="secondary"):
                    send_command(selected_device, "open_door")
            with col4:
                if st.button("🔒 Close", use_container_width=True, type="secondary"):
                    send_command(selected_device, "close_door")
        
        st.markdown("---")
        st.markdown("#### Dashboard v1.0")
        st.caption(f"Last update: {datetime.now().strftime('%H:%M:%S')}")

def render_overview_tab():
    """Tab Overview - Ringkasan sistem"""
    st.header("📊 System Overview")
    
    # Metrics cards
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        device_count = len(st.session_state.devices)
        st.metric("Connected Devices", device_count, 
                 delta=None if device_count == 0 else f"{device_count} online")
    
    with col2:
        active_alerts = len([a for a in st.session_state.security_alerts 
                           if a['timestamp'] > datetime.now() - timedelta(hours=24)])
        st.metric("24h Alerts", active_alerts, 
                 delta_color="inverse" if active_alerts > 0 else "off")
    
    with col3:
        if st.session_state.sensor_data['distance']:
            last_dist = st.session_state.sensor_data['distance'][-1]['value']
            st.metric("Distance", f"{last_dist} cm")
        else:
            st.metric("Distance", "N/A")
    
    with col4:
        if st.session_state.current_package['resi']:
            status = st.session_state.current_package['status']
            st.metric("Delivery Status", status)
        else:
            st.metric("Delivery Status", "Idle")
    
    st.markdown("---")
    
    # Grafik sensor data
    if st.session_state.sensor_data['distance']:
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("📈 Distance Sensor")
            df_distance = pd.DataFrame(st.session_state.sensor_data['distance'])
            if not df_distance.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_distance['timestamp'],
                    y=df_distance['value'],
                    mode='lines+markers',
                    name='Distance (cm)',
                    line=dict(color='#FF4B4B')
                ))
                fig.update_layout(
                    height=300,
                    xaxis_title="Time",
                    yaxis_title="Distance (cm)",
                    template="plotly_white"
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            st.subheader("📶 WiFi Signal")
            df_rssi = pd.DataFrame(st.session_state.sensor_data['wifi_rssi'])
            if not df_rssi.empty:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_rssi['timestamp'],
                    y=df_rssi['value'],
                    mode='lines+markers',
                    name='RSSI (dBm)',
                    line=dict(color='#4B8DFF')
                ))
                fig.update_layout(
                    height=300,
                    xaxis_title="Time",
                    yaxis_title="Signal Strength (dBm)",
                    template="plotly_white"
                )
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No sensor data available. Connect devices to see real-time metrics.")

def render_delivery_tab():
    """Tab Delivery Control - Kontrol pengiriman"""
    st.header("🚚 Delivery Control")
    
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # Form pengiriman manual
        with st.container(border=True):
            st.subheader("Manual Delivery")
            
            with st.form("delivery_form"):
                resi = st.text_input("Resi Number", placeholder="Enter resi number...")
                
                col_a, col_b = st.columns(2)
                with col_a:
                    is_cod = st.checkbox("COD Payment")
                with col_b:
                    if is_cod:
                        amount = st.number_input("Amount", min_value=0.0, value=100000.0, step=1000.0)
                        slot = st.selectbox("Money Slot", [1, 2])
                
                submitted = st.form_submit_button("Start Delivery", type="primary")
                
                if submitted:
                    # Cari device ESP32 utama
                    esp32_devices = [d for d in st.session_state.devices 
                                   if st.session_state.devices[d]['type'] == 'ESP32']
                    
                    if esp32_devices:
                        device_id = esp32_devices[0]
                        payload = {"resi": resi, "is_cod": is_cod}
                        if is_cod:
                            payload.update({"amount": amount, "money_slot": slot})
                        
                        if send_command(device_id, "validate_resi", payload):
                            st.success(f"Delivery started for resi: {resi}")
                    else:
                        st.warning("No ESP32 device connected")
        
        # Status paket saat ini
        st.subheader("Current Package Status")
        package = st.session_state.current_package
        
        if package['resi']:
            with st.container(border=True):
                cols = st.columns([2, 1, 1])
                with cols[0]:
                    st.markdown(f"**Resi:** {package['resi']}")
                    st.markdown(f"**Status:** {package['status']}")
                with cols[1]:
                    if package['is_cod']:
                        st.markdown(f"**Amount:** Rp{package['amount']:,.0f}")
                    else:
                        st.markdown("**Type:** Regular")
                with cols[2]:
                    if package['timestamp']:
                        st.caption(f"Updated: {package['timestamp'].strftime('%H:%M:%S')}")
        else:
            st.info("No active delivery")
    
    with col2:
        # Kontrol pembayaran
        with st.container(border=True):
            st.subheader("💰 Payment Control")
            
            slot = st.selectbox("Select Money Slot", [1, 2], key="payment_slot")
            
            if st.button("💵 Dispense Money", use_container_width=True, type="primary"):
                esp32_devices = [d for d in st.session_state.devices 
                               if st.session_state.devices[d]['type'] == 'ESP32']
                if esp32_devices:
                    if send_command(esp32_devices[0], "dispense_money", {"slot": slot}):
                        st.success(f"Dispensing from slot {slot}")
                else:
                    st.warning("No ESP32 device connected")
            
            st.markdown("---")
            
            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("🔄 Test Servo", use_container_width=True):
                    esp32_devices = [d for d in st.session_state.devices 
                                   if st.session_state.devices[d]['type'] == 'ESP32']
                    if esp32_devices:
                        send_command(esp32_devices[0], "test_servo", {"angle": 90})
            with col_b:
                if st.button("🔊 Test Buzzer", use_container_width=True):
                    esp32_devices = [d for d in st.session_state.devices 
                                   if st.session_state.devices[d]['type'] == 'ESP32']
                    if esp32_devices:
                        send_command(esp32_devices[0], "test_buzzer")

def render_camera_tab():
    """Tab Camera - Monitoring ESP32-CAM"""
    st.header("📷 ESP32-CAM Monitoring")
    
    # Cari device kamera
    cam_devices = [d for d in st.session_state.devices 
                   if st.session_state.devices[d]['type'] == 'ESP32-CAM']
    
    if not cam_devices:
        st.info("No camera devices connected. Ensure ESP32-CAM is powered and connected to MQTT.")
        return
    
    selected_cam = st.selectbox("Select Camera", cam_devices)
    
    if selected_cam:
        cam_info = st.session_state.devices[selected_cam]
        
        # Status kamera
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Camera", selected_cam)
        with col2:
            last_seen = cam_info['last_seen']
            time_diff = (datetime.now() - last_seen).total_seconds()
            status = "🟢 Online" if time_diff < 30 else "🟡 Idle" if time_diff < 120 else "🔴 Offline"
            st.metric("Status", status)
        with col3:
            if 'free_heap' in cam_info['status']:
                st.metric("Free Memory", f"{cam_info['status']['free_heap']:,} bytes")
        
        # Feed placeholder (bisa diganti dengan gambar aktual dari MQTT)
        st.markdown("---")
        st.subheader("Camera Feed")
        
        with st.container(height=400):
            # Placeholder untuk feed kamera
            # Di implementasi nyata, ini akan menampilkan gambar dari MQTT
            st.markdown("""
            <div style='display: flex; justify-content: center; align-items: center; 
                        height: 100%; background-color: #f0f2f6; border-radius: 10px;'>
                <div style='text-align: center;'>
                    <div style='font-size: 48px; margin-bottom: 16px;'>📷</div>
                    <h3 style='color: #666;'>Camera Feed</h3>
                    <p style='color: #888;'>Live feed will appear here when available</p>
                </div>
            </div>
            """, unsafe_allow_html=True)
        
        # Kontrol kamera
        st.markdown("---")
        st.subheader("Camera Controls")
        
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("📸 Capture Photo", use_container_width=True, type="primary"):
                send_command(selected_cam, "capture", {"purpose": "manual_capture"})
        with col2:
            quality = st.slider("Quality", 1, 63, 12, key="cam_quality")
        with col3:
            if st.button("⚙️ Update Settings", use_container_width=True):
                send_command(selected_cam, "configure", {"quality": quality})

def render_logs_tab():
    """Tab Logs - Sistem log"""
    st.header("📝 System Logs")
    
    # Filter logs
    col1, col2, col3 = st.columns(3)
    with col1:
        log_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "ALERT"]
        selected_levels = st.multiselect(
            "Log Level",
            options=log_levels,
            default=["INFO", "WARNING", "ERROR"]
        )
    
    with col2:
        devices = list(st.session_state.devices.keys()) + ["Dashboard"]
        selected_devices = st.multiselect(
            "Device",
            options=devices,
            default=devices[:3] if devices else []
        )
    
    with col3:
        log_limit = st.slider("Show Last N Logs", 10, 500, 100)
    
    # Filter logs berdasarkan seleksi
    filtered_logs = [
        log for log in st.session_state.system_logs[-log_limit:]
        if log['level'] in selected_levels
        and (not selected_devices or log['device'] in selected_devices)
    ]
    
    # Tampilkan logs
    if filtered_logs:
        # Container untuk logs
        log_container = st.container(height=500, border=True)
        
        with log_container:
            for log in reversed(filtered_logs):
                # Tentukan warna berdasarkan level
                color_map = {
                    "DEBUG": "#888",
                    "INFO": "#4B8DFF",
                    "WARNING": "#FFA500",
                    "ERROR": "#FF4B4B",
                    "ALERT": "#FF1493"
                }
                color = color_map.get(log['level'], "#888")
                
                # Tampilkan log entry
                cols = st.columns([1, 2, 3, 2])
                with cols[0]:
                    st.markdown(f"<span style='color:{color}; font-weight:bold;'>{log['level']}</span>", 
                               unsafe_allow_html=True)
                with cols[1]:
                    st.text(log['device'])
                with cols[2]:
                    st.text(log['message'][:80] + "..." if len(log['message']) > 80 else log['message'])
                with cols[3]:
                    st.caption(log['timestamp'].strftime("%H:%M:%S"))
        
        # Ekspor logs
        st.markdown("---")
        col1, col2 = st.columns([3, 1])
        with col2:
            if st.button("📥 Export Logs", use_container_width=True):
                if filtered_logs:
                    df = pd.DataFrame(filtered_logs)
                    csv = df.to_csv(index=False)
                    
                    st.download_button(
                        label="Download CSV",
                        data=csv,
                        file_name=f"jmailbox_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                        mime="text/csv",
                        use_container_width=True
                    )
    else:
        st.info("No logs available with current filters")

def render_alerts_tab():
    """Tab Alerts - Notifikasi keamanan"""
    st.header("🚨 Security Alerts")
    
    if not st.session_state.security_alerts:
        st.info("No security alerts detected.")
        return
    
    # Ringkasan alert
    col1, col2, col3 = st.columns(3)
    
    with col1:
        total_alerts = len(st.session_state.security_alerts)
        st.metric("Total Alerts", total_alerts)
    
    with col2:
        today_alerts = len([a for a in st.session_state.security_alerts 
                          if a['timestamp'].date() == datetime.now().date()])
        st.metric("Today", today_alerts)
    
    with col3:
        high_alerts = len([a for a in st.session_state.security_alerts 
                         if a.get('severity', 1) >= 3])
        st.metric("High Severity", high_alerts, delta_color="inverse")
    
    st.markdown("---")
    
    # Daftar alert
    st.subheader("Recent Alerts")
    
    # Urutkan dari yang terbaru
    recent_alerts = sorted(st.session_state.security_alerts, 
                         key=lambda x: x['timestamp'], 
                         reverse=True)[:20]
    
    for alert in recent_alerts:
        # Tentukan warna berdasarkan severity
        severity = alert.get('severity', 1)
        if severity >= 3:
            border_color = "#FF4B4B"
            icon = "🔴"
            severity_text = "HIGH"
        elif severity == 2:
            border_color = "#FFA500"
            icon = "🟡"
            severity_text = "MEDIUM"
        else:
            border_color = "#4B8DFF"
            icon = "🔵"
            severity_text = "LOW"
        
        # Tampilkan alert card
        with st.container(border=True):
            cols = st.columns([1, 4, 2, 1])
            with cols[0]:
                st.markdown(f"<h2>{icon}</h2>", unsafe_allow_html=True)
            with cols[1]:
                st.markdown(f"**{alert['reason']}**")
                st.caption(alert.get('message', ''))
                st.caption(f"Device: {alert['device']}")
            with cols[2]:
                time_diff = datetime.now() - alert['timestamp']
                if time_diff.days > 0:
                    time_text = f"{time_diff.days} day(s) ago"
                elif time_diff.seconds > 3600:
                    time_text = f"{time_diff.seconds // 3600} hour(s) ago"
                else:
                    time_text = f"{time_diff.seconds // 60} minute(s) ago"
                st.caption(time_text)
            with cols[3]:
                st.markdown(f"<span style='color:{border_color}; font-weight:bold;'>{severity_text}</span>", 
                           unsafe_allow_html=True)

def render_config_tab():
    """Tab Configuration - Konfigurasi sistem"""
    st.header("⚙️ System Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Konfigurasi dashboard
        with st.container(border=True):
            st.subheader("Dashboard Settings")
            
            # Versi dashboard
            st.text_input("Dashboard Version", value="1.0.0", disabled=True)
            
            # Refresh interval
            refresh_interval = st.slider(
                "Auto-refresh Interval (seconds)",
                min_value=5,
                max_value=60,
                value=30,
                step=5
            )
            
            # Tema warna
            st.markdown("#### Color Theme")
            theme_cols = st.columns(5)
            themes = [
                ("Orange", "#FF6B35"),
                ("Blue", "#4B8DFF"),
                ("Green", "#00C851"),
                ("Purple", "#9C27B0"),
                ("Red", "#FF4B4B")
            ]
            
            selected_theme = "Blue"  # Default
            
            for i, (name, color) in enumerate(themes):
                with theme_cols[i]:
                    if st.button(
                        name,
                        use_container_width=True,
                        type="primary" if name == selected_theme else "secondary"
                    ):
                        selected_theme = name
            
            # Mode tampilan
            st.markdown("#### Display Mode")
            display_mode = st.radio(
                "Select display mode",
                ["Light", "Dark", "Auto"],
                horizontal=True
            )
            
            if st.button("💾 Save Settings", use_container_width=True):
                st.success("Settings saved!")
    
    with col2:
        # Konfigurasi MQTT
        with st.container(border=True):
            st.subheader("MQTT Configuration")
            
            broker = st.text_input(
                "Broker URL",
                value=MQTT_BROKER,
                help="MQTT broker address"
            )
            
            port = st.number_input(
                "Port",
                min_value=1,
                max_value=65535,
                value=MQTT_PORT
            )
            
            st.markdown("#### Topics")
            for topic in MQTT_TOPICS:
                st.code(topic, language="text")
            
            if st.button("🔗 Test Connection", use_container_width=True):
                if init_mqtt():
                    st.success("Connection successful!")
                else:
                    st.error("Connection failed")
        
        # Device management
        with st.container(border=True):
            st.subheader("Device Management")
            
            if st.session_state.devices:
                for device_id, info in st.session_state.devices.items():
                    with st.expander(f"{device_id} ({info['type']})"):
                        st.json(info['status'])
                        
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button("🔄 Reboot", key=f"reboot_{device_id}"):
                                send_command(device_id, "reboot")
                        with col_b:
                            if st.button("🗑️ Remove", key=f"remove_{device_id}", type="secondary"):
                                if device_id in st.session_state.devices:
                                    del st.session_state.devices[device_id]
                                    st.rerun()
            else:
                st.info("No devices connected")

# ==================== APLIKASI UTAMA ====================
def main():
    """Fungsi utama aplikasi"""
    
    # Inisialisasi MQTT
    if not st.session_state.mqtt_connected:
        init_mqtt()
    
    # Proses pesan MQTT yang masuk
    process_mqtt_messages()
    
    # Render sidebar
    render_sidebar()
    
    # Title dan tabs
    st.title("📦 J-MAILBOX Monitoring Dashboard")
    
    # Buat tabs sesuai desain
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Overview",
        "🚚 Delivery Control",
        "📷 Camera",
        "📝 Logs",
        "🚨 Alerts",
        "⚙️ Configuration"
    ])
    
    # Render setiap tab
    with tab1:
        render_overview_tab()
    
    with tab2:
        render_delivery_tab()
    
    with tab3:
        render_camera_tab()
    
    with tab4:
        render_logs_tab()
    
    with tab5:
        render_alerts_tab()
    
    with tab6:
        render_config_tab()
    
    # Auto-refresh berdasarkan interval
    if st.session_state.get('auto_refresh', False):
        time.sleep(st.session_state.get('refresh_interval', 30))
        st.rerun()

# ==================== JALANKAN APLIKASI ====================
if __name__ == "__main__":
    main()
