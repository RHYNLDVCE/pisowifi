# PisoWifi Development Project

A comprehensive, hardware-integrated captive portal and internet vending machine system. This project allows you to manage a "Piso WiFi" machine, controlling network access based on inserted coins, managing bandwidth, and offering a robust admin dashboard for monitoring and configuration.

## Features

*   **Captive Portal**: A public-facing portal where users can connect, insert coins, and gain internet access.
*   **Hardware Integration**: Communicates with hardware coin slots via GPIO (`OPi.GPIO`), designed for Orange Pi / Raspberry Pi SBCs.
*   **Network & Bandwidth Management**: Built-in firewall control, global speed limiters, gaming mode (UDP prioritization), and auto-pause for inactive users.
*   **Admin Dashboard**: A modern, responsive dashboard with Light/Dark mode support to monitor active users, revenue, device health (CPU, RAM, Temp), and system logs.
*   **Loyalty Points System**: Users earn points based on coin insertions, which can be redeemed for time promos.
*   **Dynamic Customization**: Configure coin rates, upload banners, and customize portal sound effects directly from the admin panel.

## Technology Stack

*   **Backend**: Python 3, FastAPI, Uvicorn
*   **Frontend**: HTML5, Vanilla CSS, Vanilla JavaScript, Jinja2 Templates, Lucide Icons
*   **Hardware/System**: `OPi.GPIO` (Orange Pi GPIO control), `iptables`/`tc` (Network Control)

## Project Structure

```text
pisowifi/
├── app/
│   ├── api/           # FastAPI route handlers (admin, portal)
│   ├── core/          # Database connection, application state
│   ├── domain/        # Core business logic models
│   ├── hardware/      # GPIO controller scripts (coin acceptor logic)
│   ├── network/       # Firewall and traffic shaping logic
│   └── services/      # Background tasks (monitoring, timeouts)
├── static/            # Public assets (CSS, JS, images, sounds)
├── templates/         # Jinja2 HTML templates
│   └── components/    # Reusable UI sections for the admin panel
├── config.json        # Application configuration state
├── requirements.txt   # Python dependencies
└── fail_safe.sh       # System recovery scripts
```

## Setup & Installation

> [!WARNING]
> This software is designed to run on a Linux-based Single Board Computer (e.g., Orange Pi) due to specific hardware GPIO and networking dependencies. Some hardware scripts cannot be run in a standard development environment.

1.  **Clone the repository:**
    ```bash
    git clone <repository-url>
    cd pisowifi
    ```

2.  **Install system dependencies (Debian/Ubuntu):**
    ```bash
    sudo apt update
    sudo apt install iptables conntrack # Ensure networking tools are installed
    ```

3.  **Install Python dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure the Application:**
    Ensure `config.json` is properly set up. It contains coin rates, timeouts, and promo settings.

## Running the Application

To run the application for development or testing (without triggering hardware faults if you are not on an Orange Pi, ensure you bypass GPIO calls in development):

```bash
sudo python3 app/main.py
```
*(Root privileges are required because the application modifies firewall rules using `iptables` and requires hardware-level access for GPIO).*

The application will start on port `80` by default.

## Admin Access

The admin portal is protected by HTTP Basic Authentication (for API docs) and a custom login page.
Navigate to `http://<device-ip>/admin` to log in and configure the machine.

## Theme Customization

The Admin interface includes a built-in toggle for Light and Dark modes. The theme preference is saved in the browser's `localStorage` and automatically persists across the dashboard, user management, and portal configuration sections.
