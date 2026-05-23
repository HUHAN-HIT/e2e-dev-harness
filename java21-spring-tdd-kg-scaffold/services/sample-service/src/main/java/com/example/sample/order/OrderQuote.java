package com.example.sample.order;

import java.math.BigDecimal;

public record OrderQuote(
        String customerId,
        BigDecimal amount,
        BigDecimal serviceFee,
        BigDecimal total
) {
}
