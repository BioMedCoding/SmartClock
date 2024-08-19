import time
import smbus2
import tkinter as tk
from datetime import datetime

# Use the I2C bus (bus 0 corresponds to GPIO0 and GPIO1)
bus = smbus2.SMBus(0)  # '0' refers to the I2C0 bus

# BMP280 I2C address
BMP280_I2C_ADDR = 0x76

def read_calibration_data():
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

def read_raw_data(reg):
    msb = bus.read_byte_data(BMP280_I2C_ADDR, reg)
    lsb = bus.read_byte_data(BMP280_I2C_ADDR, reg + 1)
    xlsb = bus.read_byte_data(BMP280_I2C_ADDR, reg + 2)
    return ((msb << 12) | (lsb << 4) | (xlsb >> 4))

def compensate_temperature(adc_T, calib):
    dig_T1, dig_T2, dig_T3 = calib[:3]

    var1 = ((((adc_T >> 3) - (dig_T1 << 1))) * (dig_T2)) >> 11
    var2 = (((((adc_T >> 4) - (dig_T1)) * ((adc_T >> 4) - (dig_T1))) >> 12) * (dig_T3)) >> 14

    t_fine = var1 + var2
    T = (t_fine * 5 + 128) >> 8

    return T / 100.0, t_fine

def compensate_pressure(adc_P, calib, t_fine):
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

def update_data():
    calib = read_calibration_data()
    raw_temp = read_raw_data(0xFA)
    raw_press = read_raw_data(0xF7)

    temp_celsius, t_fine = compensate_temperature(raw_temp, calib)
    press_hpa = compensate_pressure(raw_press, calib, t_fine)

    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    label_temp.config(text=f"Temperature: {temp_celsius:.2f} °C")
    label_press.config(text=f"Pressure: {press_hpa:.2f} hPa")
    label_time.config(text=current_time)

    root.after(5000, update_data)  # Update every 5 seconds

# Tkinter GUI setup
root = tk.Tk()
root.title("BMP280 Sensor Data")
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
