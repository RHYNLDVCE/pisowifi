from services.billing_service import BillingService
from services.session_service import SessionService
from services.admin_service import AdminService
from infrastructure.network_scanner import NetworkScanner
from infrastructure.system_ops import SystemOps

# Initialize Singletons
_billing_service = BillingService()
_session_service = SessionService(_billing_service)
_network_scanner = NetworkScanner()
_system_ops = SystemOps()
_admin_service = AdminService()

def get_session_service() -> SessionService:
    return _session_service

def get_network_scanner() -> NetworkScanner:
    return _network_scanner

def get_system_ops() -> SystemOps:
    return _system_ops

def get_admin_service() -> AdminService:
    return _admin_service