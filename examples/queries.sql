SELECT period, value, value_text, last_updated
FROM boe.main.observations(['IUDBEDR'],
  start_date := '2024-01-02', end_date := '2024-01-05')
ORDER BY period;
