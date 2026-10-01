package com.lukk.ascend.ai.agent.test;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.junit.jupiter.api.extension.AfterEachCallback;
import org.junit.jupiter.api.extension.BeforeEachCallback;
import org.junit.jupiter.api.extension.ExtensionContext;
import org.slf4j.LoggerFactory;

import java.util.List;

public final class LogCapture implements BeforeEachCallback, AfterEachCallback {

    private final Logger logger;
    private final ListAppender<ILoggingEvent> appender = new ListAppender<>();
    private Level previousLevel;

    private LogCapture(Class<?> loggerOwner) {
        this.logger = (Logger) LoggerFactory.getLogger(loggerOwner);
    }

    public static LogCapture forClass(Class<?> loggerOwner) {
        return new LogCapture(loggerOwner);
    }

    @Override
    public void beforeEach(ExtensionContext context) {
        previousLevel = logger.getLevel();
        logger.setLevel(Level.DEBUG);
        appender.list.clear();
        appender.start();
        logger.addAppender(appender);
    }

    @Override
    public void afterEach(ExtensionContext context) {
        logger.detachAppender(appender);
        appender.stop();
        logger.setLevel(previousLevel);
    }

    public List<String> messages() {
        return appender.list.stream()
                .map(ILoggingEvent::getFormattedMessage)
                .toList();
    }

    public List<String> messagesAt(Level level) {
        return appender.list.stream()
                .filter(event -> event.getLevel() == level)
                .map(ILoggingEvent::getFormattedMessage)
                .toList();
    }
}
