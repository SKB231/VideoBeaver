package main

import (
	"context"
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/SKB231/VideoBeaver/ProcessService/handler"
	"github.com/SKB231/VideoBeaver/ProcessService/s3client"
	"github.com/SKB231/VideoBeaver/ProcessService/sqs"
)

func main() {
	// Parse mode flag - allows running separate containers for probe vs compress
	mode := flag.String("mode", "", "Processing mode: 'probe' or 'compress' (uses corresponding SQS_*_QUEUE_URL)")
	flag.Parse()

	// Determine queue URL based on mode
	var queueURL string
	var workerCount int

	switch *mode {
	case "probe":
		queueURL = os.Getenv("SQS_PROBE_QUEUE_URL")
		workerCount = 4 // Probe jobs are fast, can handle more concurrently
		if queueURL == "" {
			log.Fatal("SQS_PROBE_QUEUE_URL environment variable is required for probe mode")
		}
	case "compress":
		queueURL = os.Getenv("SQS_COMPRESS_QUEUE_URL")
		workerCount = 2 // Compress jobs are CPU-intensive, limit concurrency
		if queueURL == "" {
			log.Fatal("SQS_COMPRESS_QUEUE_URL environment variable is required for compress mode")
		}
	default:
		// Fallback to single queue mode for backwards compatibility
		queueURL = os.Getenv("SQS_QUEUE_URL")
		workerCount = 2
		if queueURL == "" {
			log.Fatal("Must specify --mode=probe or --mode=compress, or set SQS_QUEUE_URL")
		}
		log.Println("Warning: Running in single-queue mode. Consider using --mode=probe or --mode=compress")
	}

	tempDir := os.Getenv("TEMP_DIR")
	if tempDir == "" {
		tempDir = os.TempDir()
	}

	// Create context that cancels on interrupt
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		sig := <-sigChan
		log.Printf("Received signal %v, shutting down...", sig)
		cancel()
	}()

	// Initialize S3 client
	s3Client, err := s3client.New(ctx)
	if err != nil {
		log.Fatalf("Failed to create S3 client: %v", err)
	}

	// Initialize message handler
	msgHandler := handler.New(s3Client, tempDir)

	// Create and start SQS consumer
	consumer, err := sqs.NewConsumer(ctx, sqs.ConsumerConfig{
		QueueURL:    queueURL,
		WorkerCount: workerCount,
	}, msgHandler.ProcessMessage)
	if err != nil {
		log.Fatalf("Failed to create SQS consumer: %v", err)
	}

	if *mode != "" {
		log.Printf("Starting video processing service in %s mode with %d workers...", *mode, workerCount)
	} else {
		log.Printf("Starting video processing service with %d workers...", workerCount)
	}

	if err := consumer.Start(ctx); err != nil && err != context.Canceled {
		log.Fatalf("Consumer error: %v", err)
	}

	log.Println("Service stopped")
}
