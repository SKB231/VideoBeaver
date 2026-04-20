package probe

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"

	"github.com/SKB231/VideoBeaver/ProcessService/models"
	"github.com/SKB231/VideoBeaver/ProcessService/s3client"
)

// ffprobeOutput represents the raw JSON output from ffprobe
type ffprobeOutput struct {
	Format  ffprobeFormat   `json:"format"`
	Streams []ffprobeStream `json:"streams"`
}

type ffprobeFormat struct {
	Filename       string `json:"filename"`
	FormatName     string `json:"format_name"`
	FormatLongName string `json:"format_long_name"`
	Duration       string `json:"duration"`
	Size           string `json:"size"`
	BitRate        string `json:"bit_rate"`
}

type ffprobeStream struct {
	Index         int    `json:"index"`
	CodecName     string `json:"codec_name"`
	CodecLongName string `json:"codec_long_name"`
	CodecType     string `json:"codec_type"` // "video" or "audio"
	Width         int    `json:"width"`
	Height        int    `json:"height"`
	Duration      string `json:"duration"`
	BitRate       string `json:"bit_rate"`
	AvgFrameRate  string `json:"avg_frame_rate"`
	RFrameRate    string `json:"r_frame_rate"`
	PixFmt        string `json:"pix_fmt"`
	SampleRate    string `json:"sample_rate"`
	Channels      int    `json:"channels"`
}

// Prober handles video probing operations
type Prober struct {
	s3Client *s3client.Client
	tempDir  string
}

// New creates a new Prober instance
func New(s3Client *s3client.Client, tempDir string) *Prober {
	return &Prober{
		s3Client: s3Client,
		tempDir:  tempDir,
	}
}

// ProbeVideo downloads a video from S3 and extracts metadata using ffprobe
func (p *Prober) ProbeVideo(ctx context.Context, bucket, s3Key string) (*models.VideoMetadata, error) {
	// Create temp file with same extension
	ext := filepath.Ext(s3Key)
	tempFile, err := os.CreateTemp(p.tempDir, "probe-*"+ext)
	if err != nil {
		return nil, fmt.Errorf("failed to create temp file: %w", err)
	}
	tempPath := tempFile.Name()
	tempFile.Close()
	defer os.Remove(tempPath)

	// Download from S3
	if err := p.s3Client.Download(ctx, bucket, s3Key, tempPath); err != nil {
		return nil, fmt.Errorf("failed to download from S3: %w", err)
	}

	// Run ffprobe
	output, err := runFFprobe(tempPath)
	if err != nil {
		return nil, fmt.Errorf("ffprobe failed: %w", err)
	}

	// Parse output
	metadata, err := parseFFprobeOutput(output, s3Key)
	if err != nil {
		return nil, fmt.Errorf("failed to parse ffprobe output: %w", err)
	}

	return metadata, nil
}

// runFFprobe executes ffprobe and returns the parsed JSON output
func runFFprobe(filePath string) (*ffprobeOutput, error) {
	cmd := exec.Command(
		"ffprobe",
		"-v", "quiet",
		"-print_format", "json",
		"-show_format",
		"-show_streams",
		filePath,
	)

	output, err := cmd.Output()
	if err != nil {
		if exitErr, ok := err.(*exec.ExitError); ok {
			return nil, fmt.Errorf("ffprobe exited with error: %s", string(exitErr.Stderr))
		}
		return nil, err
	}

	var result ffprobeOutput
	if err := json.Unmarshal(output, &result); err != nil {
		return nil, fmt.Errorf("failed to parse ffprobe JSON: %w", err)
	}

	return &result, nil
}

// parseFFprobeOutput converts raw ffprobe output to our VideoMetadata model
func parseFFprobeOutput(output *ffprobeOutput, filename string) (*models.VideoMetadata, error) {
	metadata := &models.VideoMetadata{
		Filename:       filename,
		FormatName:     output.Format.FormatName,
		FormatLongName: output.Format.FormatLongName,
		Duration:       parseFloat(output.Format.Duration),
		SizeBytes:      parseInt64(output.Format.Size),
		BitRate:        parseInt64(output.Format.BitRate),
		VideoStreams:   []models.VideoStream{},
		AudioStreams:   []models.AudioStream{},
	}

	for _, stream := range output.Streams {
		switch stream.CodecType {
		case "video":
			frameRate := stream.AvgFrameRate
			if frameRate == "" || frameRate == "0/0" {
				frameRate = stream.RFrameRate
			}

			duration := parseFloatPtr(stream.Duration)
			bitRate := parseInt64Ptr(stream.BitRate)

			metadata.VideoStreams = append(metadata.VideoStreams, models.VideoStream{
				Index:         stream.Index,
				CodecName:     stream.CodecName,
				CodecLongName: stream.CodecLongName,
				Width:         stream.Width,
				Height:        stream.Height,
				Duration:      duration,
				BitRate:       bitRate,
				FrameRate:     frameRate,
				PixFmt:        stream.PixFmt,
			})

		case "audio":
			duration := parseFloatPtr(stream.Duration)
			bitRate := parseInt64Ptr(stream.BitRate)
			sampleRate := parseIntPtr(stream.SampleRate)
			channels := &stream.Channels

			metadata.AudioStreams = append(metadata.AudioStreams, models.AudioStream{
				Index:         stream.Index,
				CodecName:     stream.CodecName,
				CodecLongName: stream.CodecLongName,
				Duration:      duration,
				BitRate:       bitRate,
				SampleRate:    sampleRate,
				Channels:      channels,
			})
		}
	}

	return metadata, nil
}

func parseFloat(s string) float64 {
	if s == "" {
		return 0
	}
	f, _ := strconv.ParseFloat(s, 64)
	return f
}

func parseFloatPtr(s string) *float64 {
	if s == "" {
		return nil
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil {
		return nil
	}
	return &f
}

func parseInt64(s string) int64 {
	if s == "" {
		return 0
	}
	i, _ := strconv.ParseInt(s, 10, 64)
	return i
}

func parseInt64Ptr(s string) *int64 {
	if s == "" {
		return nil
	}
	i, err := strconv.ParseInt(s, 10, 64)
	if err != nil {
		return nil
	}
	return &i
}

func parseIntPtr(s string) *int {
	if s == "" {
		return nil
	}
	i, err := strconv.Atoi(s)
	if err != nil {
		return nil
	}
	return &i
}
