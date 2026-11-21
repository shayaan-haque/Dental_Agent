# Dental Appointment Agent

A web app for finding available dentists, booking a visit through chat, and viewing saved appointments.

## Video walkthroughs

[Watch both walkthroughs in your browser](https://shayaan-haque.github.io/Dental_Agent/)

- **AWS deployment walkthrough (1:00)** — Sign in, search for an available dentist, book a visit, and see it in My appointments. [Download MP4](docs/demo/dental-agent-aws-walkthrough.mp4)
- **Phone-to-laptop booking demo (0:31)** — Book on a phone, then sign in on a laptop to see the same saved appointment. [Download MP4](docs/demo/dental-agent-phone-to-laptop.mp4)

[Read the video descriptions and download instructions](docs/demo/README.md).

## Demo deployment

React and Nginx served the frontend, and Nginx forwarded API requests to FastAPI. Docker Compose ran both services on Amazon EC2 using images stored in Amazon ECR. The backend saved appointments in PostgreSQL on Amazon RDS. A Cloudflare Quick Tunnel supplied the temporary HTTPS link.

See the [frontend README](frontend/README.md) for more on the app.
