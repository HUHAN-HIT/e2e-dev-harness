package com.example.sample.order;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class OrderQuoteServiceTest {

    private final OrderQuoteService service = new OrderQuoteService();

    @Test
    void quotesOrderWithFivePercentServiceFee() {
        OrderQuote quote = service.quote(new CreateOrderRequest("customer-1", new BigDecimal("100.00")));

        assertThat(quote.customerId()).isEqualTo("customer-1");
        assertThat(quote.amount()).isEqualByComparingTo("100.00");
        assertThat(quote.serviceFee()).isEqualByComparingTo("5.00");
        assertThat(quote.total()).isEqualByComparingTo("105.00");
    }

    @Test
    void rejectsNonPositiveAmount() {
        CreateOrderRequest request = new CreateOrderRequest("customer-1", BigDecimal.ZERO);

        assertThatThrownBy(() -> service.quote(request))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("amount must be positive");
    }
}
