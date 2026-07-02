"""Punto de entrada para el servidor de desarrollo Flask."""
import os
from app import create_app

env = os.environ.get("FLASK_ENV", "development")
app = create_app(env)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
