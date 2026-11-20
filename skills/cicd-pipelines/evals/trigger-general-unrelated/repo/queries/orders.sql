SELECT c.name, COUNT(*) AS order_count
FROM customers c
JOIN orders o ON o.customer_id = c.id
JOIN order_lines l ON l.order_id = o.id
GROUP BY c.name;
