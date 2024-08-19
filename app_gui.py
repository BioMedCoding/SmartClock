import time
import smbus2
import tkinter as tk
import threading
from datetime import datetime

# Timeout function to get user input with default selection
def get_sensor_choice(default='aht10', timeout=20):
    print(f"Which sensor is connected? (bmp280/aht10) [Default: {default}]")
    sensor = None

    def ask():
        nonlocal sensor
        sensor = input().strip().lower() or default

    thread = threading.Thread(target=ask)
    thread.daemon = True  # Daemonize thread to ensure it exits if main thread exits
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        print(f"No input received. Defaulting to {default}.")
        return default
    return sensor

# Only ask the sensor choice once
sensor_choice = get_sensor_choice()

# Use the I2C bus (bus 0 corresponds to GPIO0 and GPIO1)
bus = smbus2.SMBus(0)  # '0' refers to the I2C0 bus

# BMP280 I2C address
BMP280_I2C_ADDR = 0x76

# AHT10 I2C address
AHT10_I2C_ADDR = 0x38

# BMP280 functions (same as before)
def read_calibration_data_bmp280():
    calib = []
    for i in range(0x88, 0x88+24):
        calib.append(bus.read_byte_data(BMP280_I2C_ADDR, i))
    calib.append(bus.read_byte_data(BMP280_I2C_ADDR, 0xA1))
    calib.append(bus.read_byte_data(BMP280_I2C_ADDR, 0xE1))
    calib.append(bus.read_byte_data(BMP280_I2C_ADDR, 0xE2))
    calib.append(bus.read_byte_data(BMP280_I2C_ADDR, 0xE3))

    dig_T1 = (calib[1] << 8) | calib[0]
    dig_T2 = (calib[3] << 8) | calib[2]
    dig_T3 = (calib[5] << 8) | calib[4]
    dig_P1 = (calib[7] << 8) | calib[6]
    dig_P2 = (calib[9] << 8) | calib[8]
    dig_P3 = (calib[11] << 8) | calib[10]
    dig_P4 = (calib[13] << 8) | calib[12]
    dig_P5 = (calib[15] << 8) | calib[14]
    dig_P6 = (calib[17] << 8) | calib[16]
    dig_P7 = (calib[19] << 8) | calib[18]
    dig_P8 = (calib[21] << 8) | calib[20]
    dig_P9 = (calib[23] << 8) | calib[22]

    return (dig_T1, dig_T2, dig_T3, dig_P1, dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9)

def read_raw_data_bmp280(reg):
    msb = bus.read_byte_data(BMP280_I2C_ADDR, reg)
    lsb = bus.read_byte_data(BMP280_I2C_ADDR, reg + 1)
    xlsb = bus.read_byte_data(BMP280_I2C_ADDR, reg + 2)
    return ((msb << 12) | (lsb << 4) | (xlsb >> 4))

def compensate_temperature_bmp280(adc_T, calib):
    dig_T1, dig_T2, dig_T3 = calib[:3]

    var1 = ((((adc_T >> 3) - (dig_T1 << 1))) * (dig_T2)) >> 11
    var2 = (((((adc_T >> 4) - (dig_T1)) * ((adc_T >> 4) - (dig_T1))) >> 12) * (dig_T3)) >> 14

    t_fine = var1 + var2
    T = (t_fine * 5 + 128) >> 8

    return T / 100.0, t_fine

def compensate_pressure_bmp280(adc_P, calib, t_fine):
    dig_P1, dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9 = calib[3:]

    var1 = (t_fine) - 128000
    var2 = var1 * var1 * dig_P6
    var2 = var2 + ((var1 * dig_P5) << 17)
    var2 = var2 + ((dig_P4) << 35)
    var1 = ((var1 * var1 * dig_P3) >> 8) + ((var1 * dig_P2) << 12)
    var1 = (((1 << 47) + var1) * (dig_P1)) >> 33

    if var1 == 0:
        return 0  # Avoid division by zero

    P = 1048576 - adc_P
    P = (((P << 31) - var2) * 3125) // var1
    var1 = ((dig_P9) * (P >> 13) * (P >> 13)) >> 25
    var2 = ((dig_P8) * P) >> 19

    P = ((P + var1 + var2) >> 8) + ((dig_P7) << 4)
    return P / 25600.0

# AHT10 functions
def initialize_aht10():
    bus.write_byte(AHT10_I2C_ADDR, 0xE1)  # Soft reset
    time.sleep(0.04)
    bus.write_byte(AHT10_I2C_ADDR, 0xA8)
    time.sleep(0.04)
    bus.write_byte(AHT10_I2C_ADDR, 0x33)
    time.sleep(0.04)

def read_data_aht10():
    bus.write_byte(AHT10_I2C_ADDR, 0xAC)
    time.sleep(0.08)
    data = bus.read_i2c_block_data(AHT10_I2C_ADDR, 0x00, 6)

    humidity = ((data[1] << 12) | (data[2] << 4) | (data[3] >> 4)) * 100 / 1048576.0
    temperature = ((data[3] & 0x0F) << 16 | data[4] << 8 | data[5]) * 200 / 1048576.0 - 50

    return temperature, humidity

# Determine which sensor functions to use
if sensor_choice == 'bmp280':
    def read_sensor():
        calib = read_calibration_data_bmp280()
        raw_temp = read_raw_data_bmp280(0xFA)
        raw_press = read_raw_data_bmp280(0xF7)
        temp_celsius, t_fine = compensate_temperature_bmp280(raw_temp, calib)
        press_hpa = compensate_pressure_bmp280(raw_press, calib, t_fine)
        return temp_celsius, press_hpa
else:  # Default to AHT10
    initialize_aht10()
    def read_sensor():
        temp_celsius, humidity = read_data_aht10()
        return temp_celsius, humidity

def update_data():
    temp_celsius, pressure_or_humidity = read_sensor()

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    label_temp.config(text=f"Temperature: {temp_celsius:.2f} °C")
    if sensor_choice == 'bmp280':
        label_press.config(text=f"Pressure: {pressure_or_humidity:.2f} hPa")
    else:
        label_press.config(text=f"Humidity: {pressure_or_humidity:.2f} %")
    label_time.config(text=current_time)

    root.after(5000, update_data)  # Update every 5 seconds

# Tkinter GUI setup
root = tk.Tk()
root.title("Sensor Data")
root.geometry("400x200")

label_time = tk.Label(root, text="", font=("Helvetica", 14))
label_time.pack(pady=10)

label_temp = tk.Label(root, text="", font=("Helvetica", 14))
label_temp.pack(pady=10)

label_press = tk.Label(root, text="", font=("Helvetica", 14))
label_press.pack(pady=10)

# Start updating the data
update_data()

# Start the Tkinter event loop
root.mainloop()
