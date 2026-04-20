package compress

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/SKB231/VideoBeaver/ProcessService/models"
	"github.com/SKB231/VideoBeaver/ProcessService/s3client"
)

// Compressor handles video compression operations
type Compressor struct {
	s3Client *s3client.Client
	tempDir  string
}

// New creates a new Compressor instance
func New(s3Client *s3client.Client, tempDir string) *Compressor {
	return &Compressor{
		s3Client: s3Client,
		tempDir:  tempDir,
	}
}

// Options contains the compression settings
type Options struct {
	VideoCodec     models.VideoCodec
	Container      models.Container
	MaxBitrateKbps *int
	KeepAudio      bool
}

// CompressResult contains the result of a compression operation
type CompressResult struct {
	OutputPath string
	OutputKey  string
}

// CompressVideo downloads a video from S3, compresses it, and uploads the result
func (c *Compressor) CompressVideo(ctx context.Context, msg *models.CompressMessage) (*CompressResult, error) {
	// Create temp files
	inputExt := filepath.Ext(msg.S3Key)
	inputFile, err := os.CreateTemp(c.tempDir, "input-*"+inputExt)
	if err != nil {
		return nil, fmt.Errorf("failed to create input temp file: %w", err)
	}
	inputPath := inputFile.Name()
	inputFile.Close()
	defer os.Remove(inputPath)

	outputExt := "." + string(msg.Container)
	outputFile, err := os.CreateTemp(c.tempDir, "output-*"+outputExt)
	if err != nil {
		return nil, fmt.Errorf("failed to create output temp file: %w", err)
	}
	outputPath := outputFile.Name()
	outputFile.Close()
	defer os.Remove(outputPath)

	// Download from S3
	if err := c.s3Client.Download(ctx, msg.S3Bucket, msg.S3Key, inputPath); err != nil {
		return nil, fmt.Errorf("failed to download from S3: %w", err)
	}

	// Build and run ffmpeg command
	opts := Options{
		VideoCodec:     msg.VideoCodec,
		Container:      msg.Container,
		MaxBitrateKbps: msg.MaxBitrateKbps,
		KeepAudio:      msg.KeepAudio,
	}

	if err := runFFmpeg(inputPath, outputPath, opts); err != nil {
		return nil, fmt.Errorf("ffmpeg failed: %w", err)
	}

	// Determine output S3 key
	outputBucket := msg.OutputS3Bucket
	if outputBucket == "" {
		outputBucket = msg.S3Bucket
	}

	outputKey := msg.OutputS3Key
	if outputKey == "" {
		outputKey = generateOutputKey(msg.S3Key, msg.Container)
	}

	// Upload to S3
	contentType := s3client.GetContentType(string(msg.Container))
	if err := c.s3Client.Upload(ctx, outputPath, outputBucket, outputKey, contentType); err != nil {
		return nil, fmt.Errorf("failed to upload to S3: %w", err)
	}

	return &CompressResult{
		OutputPath: outputPath,
		OutputKey:  outputKey,
	}, nil
}

// GeneratePresignedURL generates a presigned download URL for the output
func (c *Compressor) GeneratePresignedURL(ctx context.Context, bucket, key string) (string, error) {
	return c.s3Client.GeneratePresignedURL(ctx, bucket, key, 24*time.Hour)
}

// runFFmpeg executes the ffmpeg command with the given options
func runFFmpeg(inputPath, outputPath string, opts Options) error {
	args := []string{
		"-i", inputPath,
		"-y", // overwrite output file
	}

	// Add video codec
	args = append(args, getVideoCodecArgs(opts.VideoCodec)...)

	// Add bitrate limit if specified
	if opts.MaxBitrateKbps != nil {
		bitrateStr := fmt.Sprintf("%dk", *opts.MaxBitrateKbps)
		args = append(args, "-b:v", bitrateStr)
		args = append(args, "-maxrate", bitrateStr)
		// Buffer size = 2x bitrate for better quality
		bufsize := fmt.Sprintf("%dk", *opts.MaxBitrateKbps*2)
		args = append(args, "-bufsize", bufsize)
	}

	// Handle audio
	if opts.KeepAudio {
		// Copy audio stream or re-encode based on container compatibility
		args = append(args, getAudioArgs(opts.Container)...)
	} else {
		args = append(args, "-an") // no audio
	}

	// Add output file
	args = append(args, outputPath)

	cmd := exec.Command("ffmpeg", args...)

	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("ffmpeg error: %s, output: %s", err, string(output))
	}

	return nil
}

// getVideoCodecArgs returns the ffmpeg arguments for the specified video codec
func getVideoCodecArgs(codec models.VideoCodec) []string {
	switch codec {
	case models.CodecH264:
		return []string{
			"-c:v", "libx264",
			"-preset", "medium",
			"-crf", "23",
		}
	case models.CodecH265:
		return []string{
			"-c:v", "libx265",
			"-preset", "medium",
			"-crf", "28",
		}
	case models.CodecVP9:
		return []string{
			"-c:v", "libvpx-vp9",
			"-crf", "30",
			"-b:v", "0", // required for CRF mode in VP9
		}
	case models.CodecAV1:
		return []string{
			"-c:v", "libaom-av1",
			"-crf", "30",
			"-cpu-used", "4", // balance between speed and quality
		}
	default:
		// Default to H.264
		return []string{
			"-c:v", "libx264",
			"-preset", "medium",
			"-crf", "23",
		}
	}
}

// getAudioArgs returns the ffmpeg arguments for audio based on container
func getAudioArgs(container models.Container) []string {
	switch container {
	case models.ContainerWebM:
		// WebM requires Opus or Vorbis audio
		return []string{"-c:a", "libopus", "-b:a", "128k"}
	case models.ContainerMKV:
		// MKV supports most audio codecs, copy if possible
		return []string{"-c:a", "copy"}
	case models.ContainerMP4, models.ContainerMOV:
		// MP4/MOV work best with AAC
		return []string{"-c:a", "aac", "-b:a", "128k"}
	default:
		return []string{"-c:a", "aac", "-b:a", "128k"}
	}
}

// generateOutputKey creates an output S3 key from the input key
func generateOutputKey(inputKey string, container models.Container) string {
	ext := filepath.Ext(inputKey)
	base := strings.TrimSuffix(inputKey, ext)
	return fmt.Sprintf("%s_compressed.%s", base, string(container))
}
