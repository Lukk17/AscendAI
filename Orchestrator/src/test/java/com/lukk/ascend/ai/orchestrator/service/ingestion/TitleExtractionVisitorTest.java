package com.lukk.ascend.ai.orchestrator.service.ingestion;

import org.commonmark.node.Heading;
import org.commonmark.node.Text;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

class TitleExtractionVisitorTest {

    @Test
    void visit_ShouldExtractFirstHeading() {
        // given
        TitleExtractionVisitor visitor = new TitleExtractionVisitor();
        Heading heading = new Heading();
        heading.setLevel(1);
        Text text = new Text("My Title");
        heading.appendChild(text);

        // when
        visitor.visit(heading);

        // then
        assertEquals("My Title", visitor.getTitle());
    }

    @Test
    void visit_ShouldReturnNull_WhenNoHeadingExists() {
        // given
        TitleExtractionVisitor visitor = new TitleExtractionVisitor();

        // then
        assertNull(visitor.getTitle());
    }
}
