# QuantAgent Architecture

Version: 1.0

Author: Devansh

Status: Frozen

---

# Vision

QuantAgent is an AI-powered Recruiting Intelligence Agent built specifically for Quantitative Trading, HFT, Hedge Funds and Financial Technology companies.

Instead of manually checking hundreds of career pages every day, QuantAgent continuously monitors recruiting sources and delivers only relevant opportunities through intelligent reports and notifications.

The objective is to completely automate recruiting intelligence.

The user should only need to:

• Add companies

• Update profile preferences

Everything else should happen automatically.

---

# Product Objectives

QuantAgent must automatically:

✓ Monitor every watched company

✓ Discover career pages

✓ Detect recruiting events

✓ Detect internships

✓ Detect graduate programs

✓ Detect new job postings

✓ Detect changes in existing opportunities

✓ Detect application deadline updates

✓ Detect removed opportunities

✓ Match opportunities against the user's profile

✓ Send professional instant alerts

✓ Send beautiful daily recruiting reports

✓ Maintain complete historical records

---

# Core Philosophy

The architecture is frozen.

Every future feature should fit inside the existing architecture.

Do NOT redesign the project.

Do NOT rename files.

Do NOT move folders.

Do NOT duplicate business logic.

Favor extension over replacement.

---

# High-Level Workflow

                    Add Company
                         │
                         ▼
                  Company Registry
                         │
                         ▼
                 Career Discovery
                         │
                         ▼
                  Page Registry
                         │
                         ▼
              Provider Detection
                         │
                         ▼
                Data Provider
         (Greenhouse / JSON / HTML)
                         │
                         ▼
                 Raw Opportunity
                         │
                         ▼
                  Normalization
                         │
                         ▼
                 SQLite Database
                         │
                         ▼
                 Profile Matching
                         │
                         ▼
                Notification Engine
                  │               │
                  ▼               ▼
           Instant Alert     Daily Report

---

# Directory Structure

app/
models/
services/
scrapers/
database/
data/
logs/
docs/

---

# app/

Contains application entry points.

No business logic.

## cli.py

Responsible only for command orchestration.

CLI must never contain scraping logic.

CLI must never contain SQL queries.

CLI only coordinates services.

---

## database.py

Responsible for

- SQLAlchemy Engine

- Base

- Session

Nothing else.

---

## config.py

Application configuration.

No secrets should be hardcoded.

---

# models/

Contains database schema.

Models must never perform scraping.

Models must never send emails.

Models describe data only.

Current models:

• Company

• Page

• Opportunity

• Notification

---

# services/

Contains business logic.

Each service has one responsibility.

---

## registry.py

Owns companies.

Responsibilities

- watch company

- remove company

- list companies

- retrieve company

No scraping.

---

## discovery.py

Finds recruiting pages.

Examples

Careers

Students

Events

Internships

Discovery never extracts jobs.

---

## extractor.py

Analyzes recruiting pages.

Responsible for discovering:

- JSON APIs

- ATS providers

- Embedded job feeds

- Structured data

Extractor never stores anything.

---

## monitor.py

Repository layer.

Owns:

Pages

Opportunities

Hashes

History

Timestamps

Deduplication

Only Monitor writes opportunities.

---

## normalizer.py

Converts provider-specific data into a common Opportunity object.

Every provider must pass through a normalizer.

---

## matcher.py

Matches opportunities against profile.yaml.

Produces

Match Score

Priority

Reason

Never performs scraping.

---

## notifier.py

Owns all notifications.

Responsibilities

Instant Alerts

Daily Report

Email Templates

Notification History

Duplicate Prevention

---

# scrapers/

Responsible for downloading raw provider data.

Scrapers never:

Write databases

Send emails

Perform matching

Supported providers

Greenhouse

Lever

Workday

Ashby

Generic JSON

Generic HTML

Providers should be reusable.

Avoid company-specific implementations whenever possible.

---

# Opportunity Lifecycle

Provider

↓

Raw Data

↓

Normalizer

↓

Opportunity

↓

Deduplication

↓

SQLite

↓

Matcher

↓

Notifier

---

# Notification System

QuantAgent provides TWO notification systems.

-------------------------------------------------

1. Instant Alerts

-------------------------------------------------

Whenever a NEW relevant opportunity appears

Company

↓

Discovery

↓

Provider

↓

Normalizer

↓

Database

↓

Profile Match

↓

Professional Email

Only NEW opportunities should trigger alerts.

Duplicate emails are never allowed.

---

Example Subject

🚨 New Opportunity — Jane Street | Quantitative Research Intern

---

The email should include

Company

Role

Location

Department

Internship / Full Time

Application Link

Deadline

AI-generated summary

Reason it matches the user's profile

Match score

Estimated urgency

Professional HTML formatting

Call-to-action button

---

-------------------------------------------------

2. Daily Recruiting Intelligence Report

-------------------------------------------------

Every morning QuantAgent sends ONE report.

This report should resemble a consulting dashboard rather than a system log.

The report should include

Executive Summary

Companies Checked

Success Rate

Failures

New Jobs

New Internships

Graduate Programs

Recruiting Events

Closed Opportunities

Application Deadlines

High Priority Matches

Medium Priority Matches

Company Activity

Recruiting Trends

System Health

AI-generated daily summary

---

Example

━━━━━━━━━━━━━━━━━━━━━━

Daily Recruiting Report

Monday • 14 July

━━━━━━━━━━━━━━━━━━━━━━

Companies Checked

48

New Opportunities

21

Internships

6

Events

4

Matches

9

Errors

1

━━━━━━━━━━━━━━━━━━━━━━

High Priority

Jane Street

Quantitative Research Intern

97%

Apply →

--------------------

Optiver

Graduate Trader

95%

Apply →

--------------------

Jump Trading

Software Engineering Intern

94%

Apply →

━━━━━━━━━━━━━━━━━━━━━━

Recruiting Events

Jane Street

Probability in Trading

London

Register →

━━━━━━━━━━━━━━━━━━━━━━

Companies Updated

Jane Street +4

Optiver +2

IMC +3

━━━━━━━━━━━━━━━━━━━━━━

AI Summary

"Jane Street was the most active company today, posting four new internships and extending one application deadline. Optiver announced two graduate openings in Amsterdam. Overall hiring activity increased compared to yesterday."

---

The email should look like a modern executive dashboard.

It should NOT resemble console output.

---

# Matching Engine

Every opportunity receives

Match Score

0–100

Priority

High

Medium

Low

Reason

Location Match

Role Match

Skill Match

Graduation Match

Visa Match

Only opportunities above the configured threshold trigger instant alerts.

---

# Historical Tracking

Every opportunity stores

First Seen

Last Seen

Last Modified

Status

Open

Closed

Updated

QuantAgent should detect

New postings

Removed postings

Changed deadlines

Changed descriptions

---

# Logging

Internal services use logging.

CLI may use print().

Errors should never terminate the monitoring pipeline.

---

# Performance

Reuse HTTP sessions.

Avoid duplicate requests.

Avoid duplicate emails.

Avoid duplicate database writes.

Network failures should retry.

One failed company must never stop remaining companies.

---

# Future Features

Resume Parsing

Resume Match Score

AI Opportunity Summary

AI Company Summary

Calendar Integration

Deadline Reminders

Slack Notifications

Discord Notifications

Telegram Notifications

Web Dashboard

Analytics

Multi-user support

Cloud Sync

---

# Engineering Rules

Before changing code ask:

Can an existing service perform this task?

Am I duplicating logic?

Am I violating Single Responsibility?

Can this feature be tested independently?

Would a senior engineer approve this design?

If not,

redesign before coding.

---

# Definition of Done

A feature is complete only if

✓ Code compiles

✓ Database remains compatible

✓ CLI remains compatible

✓ No duplicated logic exists

✓ No TODO placeholders remain

✓ No dead code exists

✓ Logging added

✓ Errors handled

✓ Tests documented

✓ Feature integrated into sync()

---

# Final User Experience

The intended workflow is

quantagent watch "Jane Street"

↓

Company added

↓

Automatic daily monitoring

↓

New internship detected

↓

Matches profile

↓

Professional instant email sent

↓

Included in next daily intelligence report

↓

Historical record updated

↓

Done

The user should never need to manually visit company career pages again.

QuantAgent should become a complete personal recruiting intelligence system.