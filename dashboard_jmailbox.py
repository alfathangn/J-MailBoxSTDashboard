import streamlit as st
import paho.mqtt.client as mqtt
import json
import time
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import threading
import base64
from PIL import Image
import io

# Page Configuration
st.set_page_config(
    page_title="J-MAILBOX Dashboard",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# MQTT Configuration
MQTT_BROKER = "broker.hivemq.com"
MQTT_PORT = 1883
MQTT_TOPICS = {
    "status": "jmailbox/+/status",
    "command": "jmailbox/+/command",
    "sensor": "jmailbox/+/sensor",
    "alert": "jmailbox/+/alert",
    "log": "jmailbox/+/log",
    "camera": "jmailbox/+/camera",
    "payment": "jmailbox/+/payment",
    "image": "jmailbox/+/image"
}

# Global variables
if 'mqtt_client' not in st.session_state:
    st.session_state.mqtt_client = None
if 'mqtt_connected' not in st.session_state:
    st.session_state.mqtt_connected = False
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'devices' not in st.session_state:
    st.session_state.devices = {}
if 'logs' not in st.session_state:
    st.session_state.logs = []
if 'alerts' not in st.session_state:
    st.session_state.alerts = []
if 'camera_images' not in st.session_state:
    st.session_state.camera_images = {}
if 'system_status' not in st.session_state:
    st.session_state.system_status = {}

# MQTT Callbacks
def on_connect(client, userdata, flags, rc):
    st.session_state.mqtt_connected = True
    for topic in MQTT_TOPICS.values():
        client.subscribe(topic, qos=1)
    
def on_message(client, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode()
    
    try:
        data = json.loads(payload)
        device_id = data.get('device', 'unknown')
        
        # Store message
        message = {
            'timestamp': datetime.now(),
            'topic': topic,
            'device': device_id,
            'data': data
        }
        st.session_state.messages.append(message)
        
        # Update device status
        if 'jmailbox/' in topic:
            base_topic = topic.split('/')[1]
            
            if base_topic not in st.session_state.devices:
                st.session_state.devices[base_topic] = {
                    'id': base_topic,
                    'last_seen': datetime.now(),
                    'status': {},
                    'type': 'ESP32' if 'cam' not in base_topic else 'ESP32-CAM'
                }
            
            st.session_state.devices[base_topic]['last_seen'] = datetime.now()
            
            # Update device data based on topic
            if 'status' in topic:
                st.session_state.devices[base_topic]['status'].update(data)
                if base_topic not in st.session_state.system_status:
                    st.session_state.system_status[base_topic] = []
                st.session_state.system_status[base_topic].append({
                    'timestamp': datetime.now(),
                    **data
                })
                
            elif 'log' in topic:
                log_entry = {
                    'timestamp': datetime.now(),
                    'device': device_id,
                    'level': data.get('level', 'INFO'),
                    'message': data.get('message', ''),
                    'state': data.get('state', '')
                }
                st.session_state.logs.append(log_entry)
                
            elif 'alert' in topic:
                alert_entry = {
                    'timestamp': datetime.now(),
                    'device': device_id,
                    'reason': data.get('reason', ''),
                    'severity': data.get('severity', 1),
                    'state': data.get('state', '')
                }
                st.session_state.alerts.append(alert_entry)
                
            elif 'image' in topic and 'image' in data:
                # Handle camera image
                try:
                    image_data = base64.b64decode(data['image'])
                    image = Image.open(io.BytesIO(image_data))
                    st.session_state.camera_images[base_topic] = {
                        'image': image,
                        'timestamp': datetime.now(),
                        'resi': data.get('resi', ''),
                        'session': data.get('session', '')
                    }
                except:
                    pass
                    
    except json.JSONDecodeError:
        pass

def send_mqtt_command(topic, command, data=None):
    if st.session_state.mqtt_client and st.session_state.mqtt_client.is_connected():
        payload = {
            'command': command,
            'timestamp': int(time.time() * 1000),
            'source': 'dashboard'
        }
        if data:
            payload.update(data)
        
        st.session_state.mqtt_client.publish(
            topic, 
            json.dumps(payload),
            qos=1
        )
        return True
    return False

# Initialize MQTT
def init_mqtt():
    if st.session_state.mqtt_client is None:
        client = mqtt.Client(client_id=f"dashboard_{int(time.time())}")
        client.on_connect = on_connect
        client.on_message = on_message
        
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, 60)
            client.loop_start()
            st.session_state.mqtt_client = client
            st.session_state.mqtt_connected = True
            return True
        except:
            return False
    return True

# Sidebar
with st.sidebar:
    st.title("📦 J-MAILBOX")
    st.markdown("---")
    
    # Connection Status
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔗 Connect MQTT"):
            if init_mqtt():
                st.success("Connected!")
            else:
                st.error("Connection failed")
    
    with col2:
        if st.button("🔄 Refresh"):
            st.rerun()
    
    # Device Selection
    st.subheader("🌐 Connected Devices")
    device_list = list(st.session_state.devices.keys())
    selected_device = st.selectbox(
        "Select Device",
        options=device_list if device_list else ["No devices"],
        index=0
    )
    
    # Quick Commands
    st.markdown("---")
    st.subheader("⚡ Quick Commands")
    
    if st.button("📡 Start Delivery"):
        if selected_device and selected_device != "No devices":
            send_mqtt_command(
                f"jmailbox/{selected_device}/command",
                "start_delivery"
            )
            st.success("Command sent!")
    
    if st.button("🚪 Open Door"):
        if selected_device and selected_device != "No devices":
            send_mqtt_command(
                f"jmailbox/{selected_device}/command",
                "open_door"
            )
    
    if st.button("🔒 Close Door"):
        if selected_device and selected_device != "No devices":
            send_mqtt_command(
                f"jmailbox/{selected_device}/command",
                "close_door"
            )
    
    if st.button("📊 System Status"):
        if selected_device and selected_device != "No devices":
            send_mqtt_command(
                f"jmailbox/{selected_device}/command",
                "system_status"
            )
    
    # System Configuration
    st.markdown("---")
    st.subheader("⚙️ Configuration")
    
    config_expander = st.expander("MQTT Settings", expanded=False)
    with config_expander:
        broker = st.text_input("Broker", value=MQTT_BROKER)
        port = st.number_input("Port", value=MQTT_PORT, min_value=1, max_value=65535)
        
        if st.button("Update Configuration"):
            # Here you would send the configuration to the device
            st.info("Configuration update feature requires device-side implementation")

# Main Dashboard
st.title("📦 J-MAILBOX Monitoring Dashboard")

# Initialize MQTT on startup
if st.session_state.mqtt_client is None:
    init_mqtt()

# Tabs
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "📊 Overview", 
    "📦 Delivery Control", 
    "📷 Camera", 
    "📝 Logs", 
    "🚨 Alerts",
    "⚙️ Configuration"
])

# Tab 1: Overview
with tab1:
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Connected Devices", len(st.session_state.devices))
        
        # Device status cards
        for device_id, device_info in list(st.session_state.devices.items())[:3]:
            with st.container(border=True):
                col_a, col_b = st.columns([3, 1])
                with col_a:
                    st.markdown(f"**{device_id}**")
                    st.caption(f"Type: {device_info['type']}")
                with col_b:
                    time_diff = (datetime.now() - device_info['last_seen']).seconds
                    if time_diff < 60:
                        st.success("🟢")
                    elif time_diff < 300:
                        st.warning("🟡")
                    else:
                        st.error("🔴")
    
    with col2:
        if st.session_state.devices:
            # System State
            status_data = []
            for device_id, device_info in st.session_state.devices.items():
                status = device_info['status'].get('state', 'UNKNOWN')
                status_data.append({
                    'Device': device_id,
                    'State': status,
                    'Type': device_info['type']
                })
            
            if status_data:
                df_status = pd.DataFrame(status_data)
                st.dataframe(df_status, use_container_width=True, hide_index=True)
    
    with col3:
        # Quick Stats
        if st.session_state.logs:
            log_levels = [log['level'] for log in st.session_state.logs[-100:]]
            level_counts = pd.Series(log_levels).value_counts()
            
            fig_levels = go.Figure(data=[go.Pie(
                labels=level_counts.index,
                values=level_counts.values,
                hole=.3
            )])
            fig_levels.update_layout(title="Recent Log Levels", height=300)
            st.plotly_chart(fig_levels, use_container_width=True)
    
    # Real-time Metrics
    st.subheader("📈 Real-time Metrics")
    
    if selected_device in st.session_state.system_status:
        device_data = st.session_state.system_status[selected_device]
        if device_data:
            df_metrics = pd.DataFrame(device_data[-20:])
            
            if 'distance' in df_metrics.columns:
                col1, col2 = st.columns(2)
                with col1:
                    fig_distance = go.Figure()
                    fig_distance.add_trace(go.Scatter(
                        x=df_metrics['timestamp'],
                        y=df_metrics['distance'],
                        mode='lines+markers',
                        name='Distance'
                    ))
                    fig_distance.update_layout(
                        title="Ultrasonic Distance",
                        xaxis_title="Time",
                        yaxis_title="Distance (cm)",
                        height=300
                    )
                    st.plotly_chart(fig_distance, use_container_width=True)
                
                with col2:
                    if 'wifi_rssi' in df_metrics.columns:
                        fig_rssi = go.Figure()
                        fig_rssi.add_trace(go.Scatter(
                            x=df_metrics['timestamp'],
                            y=df_metrics['wifi_rssi'],
                            mode='lines+markers',
                            name='WiFi RSSI'
                        ))
                        fig_rssi.update_layout(
                            title="WiFi Signal Strength",
                            xaxis_title="Time",
                            yaxis_title="RSSI (dBm)",
                            height=300
                        )
                        st.plotly_chart(fig_rssi, use_container_width=True)

# Tab 2: Delivery Control
with tab2:
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("🚚 Delivery Management")
        
        # Manual Resi Input
        with st.form("manual_delivery_form"):
            st.markdown("#### Manual Delivery Start")
            
            resi = st.text_input("Resi Number", placeholder="Enter resi number...")
            
            col_a, col_b = st.columns(2)
            with col_a:
                is_cod = st.checkbox("COD Payment")
            
            with col_b:
                if is_cod:
                    amount = st.number_input("Amount", value=100000.0, min_value=0.0)
                    slot = st.selectbox("Money Slot", [1, 2])
            
            submitted = st.form_submit_button("Start Delivery")
            
            if submitted and selected_device and selected_device != "No devices":
                payload = {
                    "command": "validate_resi",
                    "resi": resi,
                    "is_cod": is_cod
                }
                if is_cod:
                    payload["amount"] = amount
                    payload["money_slot"] = slot
                
                send_mqtt_command(
                    f"jmailbox/{selected_device}/command",
                    "validate_resi",
                    payload
                )
                st.success(f"Delivery started for resi: {resi}")
    
    with col2:
        st.subheader("💰 Payment Control")
        
        with st.container(border=True):
            slot = st.selectbox("Select Money Slot", [1, 2], key="payment_slot")
            
            if st.button("💵 Dispense Money", use_container_width=True):
                if selected_device and selected_device != "No devices":
                    send_mqtt_command(
                        f"jmailbox/{selected_device}/command",
                        "dispense_money",
                        {"slot": slot}
                    )
                    st.success(f"Dispensing from slot {slot}")
            
            if st.button("🔄 Test Servo", use_container_width=True):
                if selected_device and selected_device != "No devices":
                    send_mqtt_command(
                        f"jmailbox/{selected_device}/command",
                        "test_servo",
                        {"angle": 90}
                    )
            
            if st.button("🔊 Test Buzzer", use_container_width=True):
                if selected_device and selected_device != "No devices":
                    send_mqtt_command(
                        f"jmailbox/{selected_device}/command",
                        "test_buzzer"
                    )
    
    # Package Tracking
    st.subheader("📦 Current Package Status")
    
    if selected_device in st.session_state.devices:
        device_status = st.session_state.devices[selected_device]['status']
        
        cols = st.columns(4)
        with cols[0]:
            st.metric("State", device_status.get('state', 'UNKNOWN'))
        with cols[1]:
            st.metric("Door Status", "OPEN" if device_status.get('door_open') else "CLOSED")
        with cols[2]:
            package = "PRESENT" if device_status.get('package_present') else "ABSENT"
            st.metric("Package", package)
        with cols[3]:
            movements = device_status.get('movement_count', 0)
            st.metric("Movements", movements)

# Tab 3: Camera
with tab3:
    st.subheader("📷 ESP32-CAM Monitoring")
    
    # Find camera devices
    camera_devices = {
        dev_id: info for dev_id, info in st.session_state.devices.items() 
        if info['type'] == 'ESP32-CAM'
    }
    
    if camera_devices:
        selected_cam = st.selectbox(
            "Select Camera",
            options=list(camera_devices.keys())
        )
        
        if selected_cam:
            # Display latest image
            if selected_cam in st.session_state.camera_images:
                image_data = st.session_state.camera_images[selected_cam]
                
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.image(
                        image_data['image'],
                        caption=f"Captured: {image_data['timestamp'].strftime('%H:%M:%S')}",
                        use_column_width=True
                    )
                
                with col2:
                    st.metric("Resi", image_data.get('resi', 'N/A'))
                    st.metric("Session", image_data.get('session', 'N/A')[:8])
                    st.metric("Device", selected_cam)
            
            # Camera Controls
            st.subheader("Camera Controls")
            
            col1, col2, col3 = st.columns(3)
            
            with col1:
                if st.button("📸 Capture Now", use_container_width=True):
                    if selected_device and selected_device != "No devices":
                        send_mqtt_command(
                            f"jmailbox/{selected_cam}/command",
                            "capture",
                            {"purpose": "manual_capture"}
                        )
            
            with col2:
                quality = st.slider("Quality", min_value=1, max_value=63, value=12, key="cam_quality")
            
            with col3:
                if st.button("⚙️ Update Settings", use_container_width=True):
                    if selected_device and selected_device != "No devices":
                        send_mqtt_command(
                            f"jmailbox/{selected_cam}/command",
                            "configure",
                            {"quality": quality}
                        )
    else:
        st.info("No camera devices connected. Ensure ESP32-CAM is powered and connected to MQTT.")

# Tab 4: Logs
with tab4:
    st.subheader("📝 System Logs")
    
    # Filter options
    col1, col2, col3 = st.columns(3)
    with col1:
        log_level_filter = st.multiselect(
            "Log Level",
            options=["DEBUG", "INFO", "WARNING", "ERROR", "ALERT"],
            default=["INFO", "WARNING", "ERROR", "ALERT"]
        )
    
    with col2:
        device_filter = st.multiselect(
            "Device",
            options=list(st.session_state.devices.keys()),
            default=list(st.session_state.devices.keys())[:3] if st.session_state.devices else []
        )
    
    with col3:
        log_limit = st.slider("Show Last N Logs", min_value=10, max_value=500, value=100)
    
    # Filter logs
    filtered_logs = [
        log for log in st.session_state.logs[-log_limit:]
        if log['level'] in log_level_filter
        and (not device_filter or log['device'] in device_filter)
    ]
    
    # Display logs
    for log in reversed(filtered_logs):
        timestamp = log['timestamp'].strftime("%H:%M:%S")
        
        # Color code based on level
        if log['level'] == 'ERROR' or log['level'] == 'ALERT':
            color = "red"
        elif log['level'] == 'WARNING':
            color = "orange"
        elif log['level'] == 'INFO':
            color = "blue"
        else:
            color = "gray"
        
        with st.container(border=True):
            cols = st.columns([1, 2, 3, 2])
            with cols[0]:
                st.markdown(f"<span style='color:{color}'>{log['level']}</span>", unsafe_allow_html=True)
            with cols[1]:
                st.text(log['device'])
            with cols[2]:
                st.text(log['message'])
            with cols[3]:
                st.caption(timestamp)
    
    # Export logs
    if st.button("📥 Export Logs"):
        if filtered_logs:
            df_logs = pd.DataFrame(filtered_logs)
            csv = df_logs.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"jmailbox_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )

# Tab 5: Alerts
with tab5:
    st.subheader("🚨 Security Alerts")
    
    if st.session_state.alerts:
        # Summary
        col1, col2, col3 = st.columns(3)
        with col1:
            total_alerts = len(st.session_state.alerts)
            st.metric("Total Alerts", total_alerts)
        
        with col2:
            high_alerts = len([a for a in st.session_state.alerts if a['severity'] >= 3])
            st.metric("High Severity", high_alerts, delta_color="inverse")
        
        with col3:
            today_alerts = len([a for a in st.session_state.alerts 
                              if a['timestamp'].date() == datetime.now().date()])
            st.metric("Today", today_alerts)
        
        # Alert List
        st.subheader("Recent Alerts")
        
        for alert in reversed(st.session_state.alerts[-20:]):
            # Determine severity color
            if alert['severity'] >= 3:
                border_color = "red"
                icon = "🔴"
            elif alert['severity'] == 2:
                border_color = "orange"
                icon = "🟡"
            else:
                border_color = "blue"
                icon = "🔵"
            
            with st.container(border=True):
                cols = st.columns([1, 3, 2, 1, 1])
                with cols[0]:
                    st.markdown(f"**{icon}**")
                with cols[1]:
                    st.markdown(f"**{alert['reason']}**")
                    st.caption(f"Device: {alert['device']}")
                with cols[2]:
                    st.text(f"State: {alert.get('state', 'N/A')}")
                with cols[3]:
                    severity_text = "HIGH" if alert['severity'] >= 3 else "MED" if alert['severity'] == 2 else "LOW"
                    st.markdown(f"<span style='color:{border_color}'><b>{severity_text}</b></span>", 
                               unsafe_allow_html=True)
                with cols[4]:
                    st.caption(alert['timestamp'].strftime("%H:%M:%S"))
    else:
        st.info("No security alerts detected.")

# Tab 6: Configuration
with tab6:
    st.subheader("⚙️ System Configuration")
    
    if selected_device and selected_device != "No devices":
        device_config = st.session_state.devices[selected_device]['status']
        
        # Configuration Form
        with st.form("device_config_form"):
            st.markdown("### Device Configuration")
            
            col1, col2 = st.columns(2)
            
            with col1:
                new_device_id = st.text_input(
                    "Device ID",
                    value=device_config.get('device', selected_device)
                )
                
                firmware = st.text_input(
                    "Firmware Version",
                    value=device_config.get('firmware', 'N/A'),
                    disabled=True
                )
                
                wifi_rssi = st.number_input(
                    "WiFi RSSI",
                    value=device_config.get('wifi_rssi', -70),
                    disabled=True
                )
            
            with col2:
                free_heap = st.number_input(
                    "Free Heap",
                    value=device_config.get('free_heap', 0),
                    disabled=True
                )
                
                uptime = st.number_input(
                    "Uptime (ms)",
                    value=device_config.get('uptime', 0),
                    disabled=True
                )
            
            # Configuration sections
            st.markdown("### MQTT Configuration")
            mqtt_col1, mqtt_col2 = st.columns(2)
            
            with mqtt_col1:
                mqtt_server = st.text_input("MQTT Server", value="broker.hivemq.com")
                mqtt_port_config = st.number_input("MQTT Port", value=1883, min_value=1, max_value=65535)
            
            with mqtt_col2:
                mqtt_user = st.text_input("Username", value="")
                mqtt_pass = st.text_input("Password", value="", type="password")
            
            # WiFi Configuration
            st.markdown("### WiFi Configuration")
            wifi_col1, wifi_col2 = st.columns(2)
            
            with wifi_col1:
                wifi_ssid = st.text_input("SSID", value="JMAILBOX-AP")
            
            with wifi_col2:
                wifi_password = st.text_input("WiFi Password", value="12345678", type="password")
            
            # Form Actions
            col1, col2, col3 = st.columns(3)
            
            with col1:
                submit_config = st.form_submit_button("💾 Save Configuration")
            
            with col2:
                submit_reboot = st.form_submit_button("🔄 Reboot Device")
            
            with col3:
                submit_reset = st.form_submit_button("🗑️ Factory Reset")
            
            if submit_config:
                config_payload = {
                    "wifi_ssid": wifi_ssid,
                    "wifi_password": wifi_password,
                    "mqtt_server": mqtt_server,
                    "mqtt_port": mqtt_port_config,
                    "device_id": new_device_id
                }
                
                send_mqtt_command(
                    f"jmailbox/{selected_device}/config",
                    "update",
                    config_payload
                )
                st.success("Configuration sent to device!")
            
            if submit_reboot:
                send_mqtt_command(
                    f"jmailbox/{selected_device}/command",
                    "reboot"
                )
                st.warning("Reboot command sent!")
            
            if submit_reset:
                if st.checkbox("⚠️ Confirm factory reset (this cannot be undone)"):
                    send_mqtt_command(
                        f"jmailbox/{selected_device}/command",
                        "reset"
                    )
                    st.error("Factory reset command sent!")

# Footer
st.markdown("---")
footer_col1, footer_col2, footer_col3 = st.columns(3)
with footer_col1:
    st.caption(f"Dashboard Version: 1.0.0")
with footer_col2:
    if st.session_state.mqtt_client:
        st.caption(f"MQTT: {'🟢 Connected' if st.session_state.mqtt_connected else '🔴 Disconnected'}")
with footer_col3:
    st.caption(f"Last update: {datetime.now().strftime('%H:%M:%S')}")

# Auto-refresh
if st.session_state.get('auto_refresh', False):
    time.sleep(2)
    st.rerun()

# Instructions
with st.expander("ℹ️ How to Use This Dashboard"):
    st.markdown("""
    ### J-MAILBOX Dashboard Guide
    
    **1. Initial Setup:**
    - Ensure both ESP32 and ESP32-CAM are connected to the same MQTT broker
    - Power on both devices and wait for them to connect to WiFi
    - Click "Connect MQTT" in the sidebar
    
    **2. Monitoring:**
    - **Overview Tab**: View real-time status of all connected devices
    - **Logs Tab**: Monitor system logs and debug messages
    - **Alerts Tab**: View security alerts and notifications
    
    **3. Control:**
    - **Delivery Control Tab**: Start deliveries, validate resi, process COD payments
    - **Camera Tab**: View camera feed and control ESP32-CAM
    - **Configuration Tab**: Update device settings and configurations
    
    **4. Important Notes:**
    - The ESP32-CAM is controlled via the main ESP32 controller
    - Camera images are only captured during delivery process
    - All security alerts are logged and displayed in real-time
    - Use the manual override commands cautiously
    """)