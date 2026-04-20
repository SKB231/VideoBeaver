package handler

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/SKB231/VideoBeaver/ProcessService/compress"
	"github.com/SKB231/VideoBeaver/ProcessService/models"
	"github.com/SKB231/VideoBeaver/ProcessService/probe"
	"github.com/SKB231/VideoBeaver/ProcessService/s3client"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
)

// Handler processes SQS messages for video operations
type Handler struct {
	prober     *probe.Prober
	compressor *compress.Compressor
	s3Client   *s3client.Client
	httpClient *http.Client
}

// New creates a new Handler instance
func New(s3Client *s3client.Client, tempDir string) *Handler {
	return &Handler{
		prober:     probe.New(s3Client, tempDir),
		compressor: compress.New(s3Client, tempDir),
		s3Client:   s3Client,
		httpClient: &http.Client{Timeout: 30 * time.Second},
	}
}

// ProcessMessage handles a single SQS message
func (h *Handler) ProcessMessage(ctx context.Context, msg types.Message) error {
	if msg.Body == nil {
		return fmt.Errorf("message body is nil")
	}

	// First, determine message type
	var wrapper models.SQSMessageWrapper
	if err := json.Unmarshal([]byte(*msg.Body), &wrapper); err != nil {
		return fmt.Errorf("failed to parse message type: %w", err)
	}

	switch wrapper.MessageType {
	case models.MessageTypeProbe:
		return h.handleProbe(ctx, *msg.Body)
	case models.MessageTypeCompress:
		return h.handleCompress(ctx, *msg.Body)
	default:
		return fmt.Errorf("unknown message type: %s", wrapper.MessageType)
	}
}

// handleProbe processes a video probe request
func (h *Handler) handleProbe(ctx context.Context, body string) error {
	var msg models.ProbeMessage
	if err := json.Unmarshal([]byte(body), &msg); err != nil {
		return fmt.Errorf("failed to parse probe message: %w", err)
	}

	log.Printf("Processing probe job: %s for s3://%s/%s", msg.JobID, msg.S3Bucket, msg.S3Key)

	// Run ffprobe
	metadata, err := h.prober.ProbeVideo(ctx, msg.S3Bucket, msg.S3Key)

	// Build result
	result := models.ProbeResult{
		JobID:  msg.JobID,
		S3Key:  msg.S3Key,
		Status: "completed",
	}

	if err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		log.Printf("Probe job %s failed: %v", msg.JobID, err)
	} else {
		result.Metadata = metadata
		log.Printf("Probe job %s completed successfully", msg.JobID)
	}

	// Send callback if URL provided
	if msg.CallbackURL != "" {
		if err := h.sendCallback(ctx, msg.CallbackURL, result); err != nil {
			log.Printf("Failed to send callback for job %s: %v", msg.JobID, err)
			// Don't return error - the probe itself succeeded
		}
	}

	return nil
}

// handleCompress processes a video compression request
func (h *Handler) handleCompress(ctx context.Context, body string) error {
	var msg models.CompressMessage
	if err := json.Unmarshal([]byte(body), &msg); err != nil {
		return fmt.Errorf("failed to parse compress message: %w", err)
	}

	log.Printf("Processing compress job: %s for s3://%s/%s", msg.JobID, msg.S3Bucket, msg.S3Key)
	log.Printf("Options: codec=%s, container=%s, maxBitrate=%v, keepAudio=%v",
		msg.VideoCodec, msg.Container, msg.MaxBitrateKbps, msg.KeepAudio)

	// Run compression
	compressResult, err := h.compressor.CompressVideo(ctx, &msg)

	// Determine output bucket
	outputBucket := msg.OutputS3Bucket
	if outputBucket == "" {
		outputBucket = msg.S3Bucket
	}

	// Build result
	result := models.CompressResult{
		JobID:  msg.JobID,
		Status: "completed",
	}

	if err != nil {
		result.Status = "failed"
		result.Error = err.Error()
		log.Printf("Compress job %s failed: %v", msg.JobID, err)
	} else {
		result.OutputS3Key = compressResult.OutputKey

		// Generate presigned URL for download
		presignedURL, urlErr := h.compressor.GeneratePresignedURL(ctx, outputBucket, compressResult.OutputKey)
		if urlErr != nil {
			log.Printf("Failed to generate presigned URL for job %s: %v", msg.JobID, urlErr)
		} else {
			result.OutputURL = presignedURL
		}

		log.Printf("Compress job %s completed successfully, output: %s", msg.JobID, compressResult.OutputKey)
	}

	// Send callback if URL provided
	if msg.CallbackURL != "" {
		if err := h.sendCallback(ctx, msg.CallbackURL, result); err != nil {
			log.Printf("Failed to send callback for job %s: %v", msg.JobID, err)
		}
	}

	return nil
}

// sendCallback sends a POST request with the result to the callback URL
func (h *Handler) sendCallback(ctx context.Context, url string, result interface{}) error {
	body, err := json.Marshal(result)
	if err != nil {
		return fmt.Errorf("failed to marshal result: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := h.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("callback request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return fmt.Errorf("callback returned status %d", resp.StatusCode)
	}

	return nil
}
