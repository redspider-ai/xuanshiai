-- 20261101_01_short_video_comment_reply
-- 短视频评论增加后台/红娘回复列 admin_reply（补齐评论“回复”能力）。
-- Run with the intended database selected (MySQL 8+).

SET NAMES utf8mb4;

SET @col_exists = (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'short_video_comment'
      AND COLUMN_NAME = 'admin_reply'
);
SET @ddl = IF(
    @col_exists = 0,
    'ALTER TABLE `short_video_comment` ADD COLUMN `admin_reply` varchar(500) DEFAULT NULL COMMENT ''红娘/后台回复内容'' AFTER `audit_status`',
    'SELECT 1'
);
PREPARE stmt FROM @ddl;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
