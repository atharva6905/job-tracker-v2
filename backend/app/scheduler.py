from apscheduler.schedulers.background import BackgroundScheduler

# Instantiated here so any module can import it.
# Started in main.py lifespan event (chunk 9).
scheduler = BackgroundScheduler()
