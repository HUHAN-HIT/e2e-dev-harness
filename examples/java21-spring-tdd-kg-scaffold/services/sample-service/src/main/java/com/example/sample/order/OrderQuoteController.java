package com.example.sample.order;

import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/orders")
public class OrderQuoteController {

    private final OrderQuoteService service;

    public OrderQuoteController(OrderQuoteService service) {
        this.service = service;
    }

    @PostMapping("/quote")
    @ResponseStatus(HttpStatus.CREATED)
    public OrderQuote quote(@Valid @RequestBody CreateOrderRequest request) {
        return service.quote(request);
    }
}
