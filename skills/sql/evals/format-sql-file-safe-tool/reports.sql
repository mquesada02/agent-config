select id, name from customers where active;

select o.id, o.total, c.name from orders o join customers c on c.id = o.customer_id where o.total > 100 order by o.total desc;

select count(*) from orders;
