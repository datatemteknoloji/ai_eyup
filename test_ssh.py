import sys
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
sys.path.append('/app')
from app.models.server import Server
from app.services.monitoring.server_connector import ServerConnector

# Config
DATABASE_URL = "postgresql://datatem:datatem123@localhost:5432/ainew"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

server = db.query(Server).filter(Server.name == "enesapp-yedek").first()
if not server:
    print("Server not found")
    sys.exit(1)

print(f"Testing {server.name} ({server.ip_address})")
connector = ServerConnector(server)
res = connector.test_connection()
print(res)
