from flask import Flask, render_template, jsonify
import RPi.GPIO as GPIO
import time
import board
import busio
import Adafruit_BMP.BMP085 as BMP085

# Setup per GPIO
GPIO.setmode(GPIO.BCM)
GPIO.setwarnings(False)
led_pin = 18                        # Pin di connessione led per il risveglio
GPIO.setup(led_pin, GPIO.OUT)

# Setup per PWM
pwm = GPIO.PWM(led_pin, 100)    # Imposta il canale PWM e la frequenza a 100 Hz
pwm.start(0)                    # Inizia con il LED spento

# Setup per BMP180
sensor = BMP085.BMP085()

# Fototransistore per rilevare la luminosità
ldr_pin = 23                    # Pin di collegamento fotoresistore
GPIO.setup(ldr_pin, GPIO.IN)

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sensor_data')
def sensor_data():
    temperature = sensor.read_temperature()
    pressure = sensor.read_pressure()
    return jsonify({'temperature': temperature, 'pressure': pressure})

@app.route('/set_alarm/<int:duration>')
def set_alarm(duration):
    """ Accende il LED con luminosità crescente per una durata specificata. """
    step_duration = duration / 100  # Calcola la durata di ogni passo
    for i in range(101):            # 0 a 100 inclusi
        pwm.ChangeDutyCycle(i)      # Cambia il duty cycle per aumentare la luminosità
        time.sleep(step_duration)
    pwm.ChangeDutyCycle(0)          # Spenga il LED al termine
    return jsonify({'status': 'Alarm executed'})

@app.route('/adjust_brightness')
def adjust_brightness():
    """ Regola la luminosità dello schermo in base alla luce ambientale. """
    light_level = GPIO.input(ldr_pin)
    if light_level == 0:  # Basso livello di luce, spegni il display
        # Cerca codice per spegnere il display da software
        pass
    else:  # Luminosità sufficiente, accendi il display
        # Cerca codice per accendere il display da software
        pass
    return jsonify({'light_level': light_level, 'status': 'Display adjusted'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)