import os
import socket

class NetworkScanner:
    def __init__(self):
        self.lease_files = [
            "/var/lib/misc/dnsmasq.leases", 
            "/var/lib/dnsmasq/dnsmasq.leases",
            "/var/lib/dhcp/dhcpd.leases"
        ]
        # Memory cache to prevent the scanner from freezing on offline devices
        self.hostname_cache = {}

    def get_dhcp_leases(self) -> dict:
        dhcp_leases = {}
        for lf in self.lease_files:
            if os.path.exists(lf):
                try:
                    with open(lf, 'r') as f:
                        for line in f:
                            parts = line.split()
                            if len(parts) >= 4:
                                dhcp_leases[parts[1].lower()] = parts[3] 
                except: pass
        return dhcp_leases

    def get_vendor_info_and_check_type(self, mac: str, ip: str, leases: dict) -> tuple[str, bool]:
        mac_clean = mac.replace(":", "").replace("-", "").upper()
        oui = mac_clean[:6]
        
        # --- VENDORS LIST ---
        vendors = {
            "200DB0": "Comfast", "40A5EF": "Comfast", "E0E1A9": "Comfast", "8C3D16": "Comfast", "00E04C": "Comfast",
            "18D6C7": "TP-Link", "CC32E5": "TP-Link", "003192": "TP-Link", "14CC20": "TP-Link",
            "50C7BF": "TP-Link", "8416F9": "TP-Link", "C025E9": "TP-Link", "E848B8": "TP-Link",
            "000AEB": "TP-Link", "001478": "TP-Link", "0019E0": "TP-Link", "001D0F": "TP-Link",
            "002127": "TP-Link", "0023CD": "TP-Link", "002586": "TP-Link", "002719": "TP-Link",
            "04F9F8": "TP-Link", "081F71": "TP-Link", "0C4B54": "TP-Link", "10FEED": "TP-Link",
            "147590": "TP-Link", "14CF92": "TP-Link", "18A6F7": "TP-Link", "1C3BF3": "TP-Link",
            "206BE7": "TP-Link", "20DCE6": "TP-Link", "246968": "TP-Link", "282CB2": "TP-Link",
            "30B5C2": "TP-Link", "349672": "TP-Link", "34E894": "TP-Link", "388345": "TP-Link",
            "3C46D8": "TP-Link", "40169F": "TP-Link", "44B32D": "TP-Link", "480EEC": "TP-Link",
            "503EAA": "TP-Link", "50BD5F": "TP-Link", "54E6FC": "TP-Link", "584120": "TP-Link",
            "60E327": "TP-Link", "6466B3": "TP-Link", "704F57": "TP-Link", "7405A5": "TP-Link",
            "74DA88": "TP-Link", "7844FD": "TP-Link", "7C8BCA": "TP-Link", "808917": "TP-Link",
            "882593": "TP-Link", "8C210A": "TP-Link", "90F652": "TP-Link", "940C6D": "TP-Link",
            "984827": "TP-Link", "98DED0": "TP-Link", "A0F3C1": "TP-Link", "A42BB0": "TP-Link",
            "AC84C6": "TP-Link", "B0487A": "TP-Link", "B0BE76": "TP-Link", "B8F883": "TP-Link",
            "C04A00": "TP-Link", "C46E1F": "TP-Link", "CC3429": "TP-Link", "D4016D": "TP-Link",
            "D807B6": "TP-Link", "DC0077": "TP-Link", "E005C5": "TP-Link", "E4C32A": "TP-Link",
            "EC086B": "TP-Link", "F4F26D": "TP-Link", "F81A67": "TP-Link", "FC70F4": "TP-Link",
            "0495E6": "Tenda", "0840F3": "Tenda", "500FF5": "Tenda", "502B73": "Tenda",
            "CC2D21": "Tenda", "C83A35": "Tenda", "0050FC": "Tenda",
            "001882": "Huawei", "00E0FC": "Huawei", "4846F1": "Huawei",
            "0015EB": "ZTE", "001E73": "ZTE", "D0DD7C": "ZTE",
            "286ED4": "FiberHome", "807D14": "FiberHome"
        }

        brand = vendors.get(oui, "Unknown")
        hostname = leases.get(mac.lower(), "")

        # --- CACHED REVERSE DNS FALLBACK ---
        if hostname == "*" or not hostname:
            if mac in self.hostname_cache:
                hostname = self.hostname_cache[mac]
            else:
                try:
                    socket.setdefaulttimeout(0.2) 
                    resolved_name = socket.gethostbyaddr(ip)[0]
                    hostname = resolved_name.split('.')[0]
                    self.hostname_cache[mac] = hostname 
                except Exception:
                    self.hostname_cache[mac] = ""
                    hostname = ""

        is_known = (brand != "Unknown")

        if brand != "Unknown" and hostname: display = f"{brand} ({hostname})"
        elif brand != "Unknown": display = brand
        elif hostname: display = hostname
        else: display = "Unknown Device"

        return display, is_known

    def is_random_mac(self, mac: str) -> bool:
        try:
            first_byte = int(mac.split(':')[0], 16)
            return (first_byte & 0x02) != 0
        except:
            return False
        
    def is_reachable(self, ip: str) -> bool:
        try:
            subprocess.check_call(['ping', '-c', '1', '-W', '1', ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except: return False

    def scan_infrastructure(self, active_user_macs: set, custom_names: dict) -> list:
        devices = []
        leases = self.get_dhcp_leases()
        import config 
        try:
            with open('/proc/net/arp') as f:
                lines = f.readlines()[1:] 
            for line in lines:
                parts = line.split()
                if len(parts) < 6: continue
                ip, hw_type, flags, mac, mask, interface = parts[:6]

                if interface == config.LAN_INTERFACE and mac != "00:00:00:00:00:00" and mac not in active_user_macs:
                    if self.is_random_mac(mac) and mac not in custom_names: continue
                    
                    display_name, is_known = self.get_vendor_info_and_check_type(mac, ip, leases)
                    name_upper = display_name.upper()
                    
                    is_likely_phone = any(kw in name_upper for kw in ["NAM", "V2", "OPPO", "VIVO", "REALME", "IPHONE", "GALAXY", "XIAOMI", "POCO", "REDMI", "ANDROID"])
                    if is_likely_phone and mac not in custom_names: continue
                    
                    devices.append({
                        "ip": ip, "mac": mac, 
                        "vendor": custom_names.get(mac, display_name),
                        "is_custom": (mac in custom_names and bool(custom_names[mac])),
                        "is_online": self.is_reachable(ip)
                    })
        except: pass
        return devices