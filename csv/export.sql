-- export queries
-- \copy () to 'csv/file.csv' WITH (FORMAT csv, DELIMITER ',',  HEADER true);

-- history
select r.name, b.order_date, b.items, b.price from bentos b join restaurants r on b.restaurant_id = r.id order by order_date desc

-- frequent
select r.name, count(*) bcount  from bentos b join restaurants r on b.restaurant_id = r.id group by r.name having count(*) > 1 order by bcount desc;

-- money spent
select r.name, sum(price) price  from bentos b join restaurants r on b.restaurant_id = r.id 
group by r.name having sum(price) > 0 order by price desc;