package main

import (
	"crypto/tls"
	"flag"
	"fmt"
	"log"
	"net/http"
)

func main() {
	host := flag.String("host", "", "Host address to bind to (default: all interfaces)")
	port := flag.Int("port", 8000, "Port number to bind to")
	certPath := flag.String("cert", "cert.pem", "Path to SSL certificate file")
	keyPath := flag.String("key", "key.pem", "Path to SSL private key file")
	useTLS := flag.Bool("tls", false, "Enable TLS")

	flag.Parse()

	if (*certPath != "" || *keyPath != "") && !*useTLS {
		log.Print("TLS cert and/or key path provided but not using TLS.")
	}

	addr := fmt.Sprintf("%s:%d", *host, *port)
	if *host == "" {
		addr = fmt.Sprintf(":%d", *port)
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/api/new-upload-key", newUploadKeyHandler)
	mux.HandleFunc("/api/upload", uploadHandler)

	fileServer := http.FileServer(http.Dir("."))
	mux.Handle("/", fileServer)

	server := &http.Server{
		Addr:    addr,
		Handler: mux,
	}

	scheme := "http"
	if *useTLS {
		server.TLSConfig = &tls.Config{MinVersion: tls.VersionTLS12}
		scheme = "https"
	}

	displayHost := *host
	if displayHost == "" {
		displayHost = "all interfaces"
	}

	log.Printf("Serving %s on %s:%d", scheme, displayHost, *port)

	if *useTLS {
		if err := server.ListenAndServeTLS(*certPath, *keyPath); err != nil {
			log.Fatalf("server error: %v", err)
		}
		return
	}

	if err := server.ListenAndServe(); err != nil {
		log.Fatalf("server error: %v", err)
	}
}
