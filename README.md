# Dental Appointment Agent

A web app for finding available dentists, booking a visit through chat, and viewing saved appointments.

## Video walkthroughs

- [AWS deployment walkthrough (1:00)](docs/demo/dental-agent-aws-walkthrough.mp4) — Sign in, check availability, and book a visit through the assistant.
- [Phone-to-laptop booking demo (0:31)](docs/demo/dental-agent-phone-to-laptop.mp4) — Book a visit on a phone, then sign in to the same account on a laptop to see the saved appointment.

## Demo deployment

React and Nginx served the frontend, and Nginx forwarded API requests to FastAPI. Docker Compose ran both services on Amazon EC2 using images stored in Amazon ECR. The backend saved appointments in PostgreSQL on Amazon RDS. A Cloudflare Quick Tunnel supplied the temporary HTTPS link.

See the [frontend README](frontend/README.md) for more on the app.
