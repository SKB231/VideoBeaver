package sqs

import (
	"context"
	"fmt"
	"log"
	"sync"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/sqs"
	"github.com/aws/aws-sdk-go-v2/service/sqs/types"
)

// MessageHandler is a function that processes a single SQS message
type MessageHandler func(ctx context.Context, msg types.Message) error

// Consumer polls an SQS queue and processes messages
type Consumer struct {
	sqsClient   *sqs.Client
	queueURL    string
	handler     MessageHandler
	workerCount int
}

// ConsumerConfig holds configuration for the SQS consumer
type ConsumerConfig struct {
	QueueURL    string
	WorkerCount int // Number of concurrent workers (default: 1)
}

// NewConsumer creates a new SQS consumer
func NewConsumer(ctx context.Context, cfg ConsumerConfig, handler MessageHandler) (*Consumer, error) {
	awsCfg, err := config.LoadDefaultConfig(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to load AWS config: %w", err)
	}

	workerCount := cfg.WorkerCount
	if workerCount <= 0 {
		workerCount = 1
	}

	return &Consumer{
		sqsClient:   sqs.NewFromConfig(awsCfg),
		queueURL:    cfg.QueueURL,
		handler:     handler,
		workerCount: workerCount,
	}, nil
}

// Start begins polling the SQS queue and processing messages
// It blocks until the context is cancelled
func (c *Consumer) Start(ctx context.Context) error {
	log.Printf("Starting SQS consumer with %d workers for queue: %s", c.workerCount, c.queueURL)

	// Channel for messages to be processed
	msgChan := make(chan types.Message, c.workerCount*2)

	// Start worker goroutines
	var wg sync.WaitGroup
	for i := 0; i < c.workerCount; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			c.worker(ctx, workerID, msgChan)
		}(i)
	}

	// Poll loop
	for {
		select {
		case <-ctx.Done():
			log.Println("Context cancelled, stopping consumer...")
			close(msgChan)
			wg.Wait()
			return ctx.Err()
		default:
			messages, err := c.receiveMessages(ctx)
			if err != nil {
				log.Printf("Error receiving messages: %v", err)
				continue
			}

			for _, msg := range messages {
				select {
				case msgChan <- msg:
				case <-ctx.Done():
					close(msgChan)
					wg.Wait()
					return ctx.Err()
				}
			}
		}
	}
}

// receiveMessages polls SQS for messages
func (c *Consumer) receiveMessages(ctx context.Context) ([]types.Message, error) {
	result, err := c.sqsClient.ReceiveMessage(ctx, &sqs.ReceiveMessageInput{
		QueueUrl:            aws.String(c.queueURL),
		MaxNumberOfMessages: 10,
		WaitTimeSeconds:     20,  // Long polling
		VisibilityTimeout:   300, // 5 minutes to process
	})
	if err != nil {
		return nil, err
	}

	return result.Messages, nil
}

// worker processes messages from the channel
func (c *Consumer) worker(ctx context.Context, id int, msgChan <-chan types.Message) {
	log.Printf("Worker %d started", id)

	for msg := range msgChan {
		if err := c.processMessage(ctx, msg); err != nil {
			log.Printf("Worker %d: failed to process message %s: %v", id, *msg.MessageId, err)
			// Message will return to queue after visibility timeout
		} else {
			// Delete successfully processed message
			if err := c.deleteMessage(ctx, msg); err != nil {
				log.Printf("Worker %d: failed to delete message %s: %v", id, *msg.MessageId, err)
			}
		}
	}

	log.Printf("Worker %d stopped", id)
}

// processMessage calls the handler for a single message
func (c *Consumer) processMessage(ctx context.Context, msg types.Message) error {
	log.Printf("Processing message: %s", *msg.MessageId)
	return c.handler(ctx, msg)
}

// deleteMessage removes a processed message from the queue
func (c *Consumer) deleteMessage(ctx context.Context, msg types.Message) error {
	_, err := c.sqsClient.DeleteMessage(ctx, &sqs.DeleteMessageInput{
		QueueUrl:      aws.String(c.queueURL),
		ReceiptHandle: msg.ReceiptHandle,
	})
	return err
}
