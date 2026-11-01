-- 20261101_01_short_video_comment_reply (down)
SET NAMES utf8mb4;

SET @col_exists = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'short_video_comment'
      AND COLUMN_NAME = 'admin_reply'
);
SET @ddl = IF(
    @col_exists = 1,
    'ALTER TABLE `short_video_comment` DROP COLUMN `admin_reply`',
    'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
