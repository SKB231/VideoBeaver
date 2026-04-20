package s3client

import (
	"context"
	"fmt"
	"io"
	"os"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

// Client wraps the S3 client with helper methods
type Client struct {
	s3Client *s3.Client
}

// New creates a new S3 client using default AWS configuration
func New(ctx context.Context) (*Client, error) {
	cfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	return &Client{
		s3Client: s3.NewFromConfig(cfg),
	}, nil
}

// NewWithConfig creates a new S3 client with a specific AWS config
func NewWithConfig(cfg aws.Config) *Client {
	return &Client{
		s3Client: s3.NewFromConfig(cfg),
	}
}

// Download downloads a file from S3 to a local path
func (c *Client) Download(ctx context.Context, bucket, key, localPath string) error {
	output, err := c.s3Client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	})
	if err != nil {
		return fmt.Errorf("failed to get object from S3: %w", err)
	}
	defer output.Body.Close()

	file, err := os.Create(localPath)
	if err != nil {
		return fmt.Errorf("failed to create local file: %w", err)
	}
	defer file.Close()

	_, err = io.Copy(file, output.Body)
	if err != nil {
		return fmt.Errorf("failed to write to local file: %w", err)
	}

	return nil
}

// Upload uploads a local file to S3
func (c *Client) Upload(ctx context.Context, localPath, bucket, key, contentType string) error {
	file, err := os.Open(localPath)
	if err != nil {
		return fmt.Errorf("failed to open local file: %w", err)
	}
	defer file.Close()

	input := &s3.PutObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
		Body:   file,
	}

	if contentType != "" {
		input.ContentType = aws.String(contentType)
	}

	_, err = c.s3Client.PutObject(ctx, input)
	if err != nil {
		return fmt.Errorf("failed to upload to S3: %w", err)
	}

	return nil
}

// GeneratePresignedURL generates a presigned URL for downloading an object
func (c *Client) GeneratePresignedURL(ctx context.Context, bucket, key string, expiration time.Duration) (string, error) {
	presignClient := s3.NewPresignClient(c.s3Client)

	request, err := presignClient.PresignGetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	}, s3.WithPresignExpires(expiration))
	if err != nil {
		return "", fmt.Errorf("failed to generate presigned URL: %w", err)
	}

	return request.URL, nil
}

// GetContentType returns the appropriate content type for a container format
func GetContentType(container string) string {
	switch container {
	case "mp4":
		return "video/mp4"
	case "webm":
		return "video/webm"
	case "mkv":
		return "video/x-matroska"
	case "mov":
		return "video/quicktime"
	default:
		return "application/octet-stream"
	}
}
