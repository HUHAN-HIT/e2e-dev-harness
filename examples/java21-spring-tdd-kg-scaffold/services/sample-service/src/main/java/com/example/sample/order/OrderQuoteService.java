package com.example.sample.order;

import java.math.BigDecimal;
import java.math.RoundingMode;
import org.springframework.stereotype.Service;

@Service
public class OrderQuoteService {

    private static final BigDecimal SERVICE_FEE_RATE = new BigDecimal("0.05");

    public OrderQuote quote(CreateOrderRequest request) {
        if (request.amount().signum() <= 0) {
            throw new IllegalArgumentException("amount must be positive");
        }
        BigDecimal fee = request.amount()
                .multiply(SERVICE_FEE_RATE)
                .setScale(2, RoundingMode.HALF_UP);
        return new OrderQuote(
                request.customerId(),
                request.amount(),
                fee,
                request.amount().add(fee)
        );
    }
}
