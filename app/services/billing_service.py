from core import state

class BillingService:
    def calculate_time_from_balance(self, balance: int) -> int:
        rates_str = state.config.get("coin_rates", "1:10,5:60,10:180,20:300")
        rates = []
        try:
            for part in rates_str.split(','):
                amt, mins = part.strip().split(':')
                rates.append((int(amt), int(mins)))
        except:
            rates = [(1, 5)] 
        
        rates.sort(key=lambda x: x[0], reverse=True)
        
        total_minutes = 0
        remaining_balance = int(balance)
        
        for amt, mins in rates:
            if amt <= 0: continue
            count = remaining_balance // amt
            if count > 0:
                total_minutes += count * mins
                remaining_balance %= amt
                
        if remaining_balance > 0:
            total_minutes += remaining_balance * 5 

        return total_minutes

    def calculate_points_from_balance(self, balance: int) -> float:
        if not state.config.get("points_enabled", False):
            return 0.0

        point_map = state.config.get("coin_point_map", {"1":0.5, "5":1, "10":3, "20":5})
        rates = []
        
        for k, v in point_map.items():
            try: rates.append((int(k), float(v)))
            except: pass
        
        rates.sort(key=lambda x: x[0], reverse=True)
        
        total_points = 0.0
        rem_balance = int(balance)
        
        for denom, val in rates:
            if denom <= 0: continue
            count = rem_balance // denom
            if count > 0:
                total_points += count * val
                rem_balance %= denom
                
        return round(total_points, 2)