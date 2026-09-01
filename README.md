# ajsclient

Automated Job Search Client

## Overview

ajsclient is a lightweight Python application designed to automate
technology job searches and produce structured Excel reports.

The application is designed to:

- Search publicly available job postings
- Extract job posting information
- Transform and normalize job data
- Apply configurable job-search criteria
- Reject postings that violate specified criteria
- Remove duplicate postings
- Calculate job match scores
- Generate timestamped Excel reports
- Maintain execution logs
- Run automatically using Windows Task Scheduler

## Architecture

Public Job Sources
        |
        v
     Extract
        |
        v
    Transform
        |
        v
     Validate
        |
        v
      Load
        |
        v
      Excel

## Status

Initial project setup.