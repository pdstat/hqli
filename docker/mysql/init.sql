-- Grant FILE privilege globally to user 'hqli'
-- This script runs at container init (mounted into /docker-entrypoint-initdb.d/)
GRANT FILE ON *.* TO 'hqli'@'%';
FLUSH PRIVILEGES;
