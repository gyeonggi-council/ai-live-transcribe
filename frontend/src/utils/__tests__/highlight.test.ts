import { highlightText, escapeRegex, escapeHtml } from '../highlight';

describe('escapeHtml', () => {
  it('should escape HTML special characters', () => {
    expect(escapeHtml('<script>alert("xss")</script>')).toBe(
      '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
    );
  });

  it('should escape ampersand', () => {
    expect(escapeHtml('Tom & Jerry')).toBe('Tom &amp; Jerry');
  });

  it('should escape single quotes', () => {
    expect(escapeHtml("It's a test")).toBe('It&#039;s a test');
  });

  it('should return empty string for empty input', () => {
    expect(escapeHtml('')).toBe('');
  });

  it('should not modify text without special characters', () => {
    expect(escapeHtml('Hello World')).toBe('Hello World');
  });
});

describe('escapeRegex', () => {
  it('should escape regex special characters', () => {
    const input = '.*+?^${}()|[]\\';
    const result = escapeRegex(input);
    // Each special character should be escaped with backslash
    expect(result).toBe('\\.\\*\\+\\?\\^\\$\\{\\}\\(\\)\\|\\[\\]\\\\');
  });

  it('should not modify text without special characters', () => {
    expect(escapeRegex('hello world')).toBe('hello world');
  });

  it('should handle mixed content', () => {
    expect(escapeRegex('hello (world)')).toBe('hello \\(world\\)');
  });
});

describe('highlightText', () => {
  describe('single keyword highlight', () => {
    it('should highlight a single keyword', () => {
      const result = highlightText('안녕하세요 여러분', '여러분');
      expect(result.html).toBe('안녕하세요 <mark class="bg-highlight">여러분</mark>');
      expect(result.hasMatch).toBe(true);
      expect(result.matchCount).toBe(1);
    });

    it('should highlight keyword at the beginning', () => {
      const result = highlightText('예산안을 심의합니다', '예산안');
      expect(result.html).toBe('<mark class="bg-highlight">예산안</mark>을 심의합니다');
      expect(result.hasMatch).toBe(true);
    });

    it('should highlight keyword at the end', () => {
      const result = highlightText('오늘의 안건', '안건');
      expect(result.html).toBe('오늘의 <mark class="bg-highlight">안건</mark>');
      expect(result.hasMatch).toBe(true);
    });
  });

  describe('multiple occurrences', () => {
    it('should highlight all occurrences of keyword', () => {
      const result = highlightText('예산 심의와 예산 집행', '예산');
      expect(result.html).toBe(
        '<mark class="bg-highlight">예산</mark> 심의와 <mark class="bg-highlight">예산</mark> 집행'
      );
      expect(result.hasMatch).toBe(true);
      expect(result.matchCount).toBe(2);
    });

    it('should highlight three occurrences', () => {
      const result = highlightText('의원 발언, 의원 질의, 의원 토론', '의원');
      expect(result.matchCount).toBe(3);
    });
  });

  describe('case insensitivity', () => {
    it('should highlight regardless of case (English)', () => {
      const result = highlightText('Hello World, HELLO world, hello WORLD', 'hello');
      expect(result.matchCount).toBe(3);
      expect(result.hasMatch).toBe(true);
    });

    it('should preserve original case in output', () => {
      const result = highlightText('Hello HELLO hello', 'hello');
      expect(result.html).toContain('>Hello<');
      expect(result.html).toContain('>HELLO<');
      expect(result.html).toContain('>hello<');
    });
  });

  describe('special characters in keyword', () => {
    it('should handle parentheses in keyword', () => {
      const result = highlightText('제1조(목적) 이 법은', '제1조(목적)');
      expect(result.html).toBe(
        '<mark class="bg-highlight">제1조(목적)</mark> 이 법은'
      );
      expect(result.hasMatch).toBe(true);
    });

    it('should handle brackets in keyword', () => {
      const result = highlightText('참조 [별표1] 참조', '[별표1]');
      expect(result.html).toBe(
        '참조 <mark class="bg-highlight">[별표1]</mark> 참조'
      );
    });

    it('should handle period in keyword', () => {
      const result = highlightText('버전 1.0.0 출시', '1.0.0');
      expect(result.html).toBe(
        '버전 <mark class="bg-highlight">1.0.0</mark> 출시'
      );
    });

    it('should handle question mark in keyword', () => {
      const result = highlightText('왜? 라고 물었다', '왜?');
      expect(result.html).toBe(
        '<mark class="bg-highlight">왜?</mark> 라고 물었다'
      );
    });
  });

  describe('XSS prevention', () => {
    it('should escape HTML in original text', () => {
      const result = highlightText('<script>alert("xss")</script>', 'alert');
      expect(result.html).not.toContain('<script>');
      expect(result.html).toContain('&lt;script&gt;');
      expect(result.html).toContain('<mark class="bg-highlight">alert</mark>');
    });

    it('should escape HTML entities in text before highlighting', () => {
      const result = highlightText('Tom & Jerry say "Hello"', 'Jerry');
      expect(result.html).toContain('&amp;');
      expect(result.html).toContain('&quot;');
      expect(result.html).toContain('<mark class="bg-highlight">Jerry</mark>');
    });

    it('should handle HTML-like content in keyword', () => {
      const result = highlightText('<div>test</div>', '<div>');
      expect(result.html).toBe(
        '<mark class="bg-highlight">&lt;div&gt;</mark>test&lt;/div&gt;'
      );
    });
  });

  describe('empty or whitespace query', () => {
    it('should return escaped text for empty query', () => {
      const result = highlightText('안녕하세요', '');
      expect(result.html).toBe('안녕하세요');
      expect(result.hasMatch).toBe(false);
      expect(result.matchCount).toBe(0);
    });

    it('should return escaped text for whitespace-only query', () => {
      const result = highlightText('안녕하세요', '   ');
      expect(result.html).toBe('안녕하세요');
      expect(result.hasMatch).toBe(false);
    });

    it('should return escaped text for null-like query', () => {
      const result = highlightText('안녕하세요', undefined as unknown as string);
      expect(result.html).toBe('안녕하세요');
      expect(result.hasMatch).toBe(false);
    });
  });

  describe('no match scenarios', () => {
    it('should return escaped text when no match found', () => {
      const result = highlightText('안녕하세요 여러분', '없는단어');
      expect(result.html).toBe('안녕하세요 여러분');
      expect(result.hasMatch).toBe(false);
      expect(result.matchCount).toBe(0);
    });
  });

  describe('edge cases', () => {
    it('should handle empty text', () => {
      const result = highlightText('', '검색어');
      expect(result.html).toBe('');
      expect(result.hasMatch).toBe(false);
    });

    it('should handle text that is exactly the query', () => {
      const result = highlightText('예산', '예산');
      expect(result.html).toBe('<mark class="bg-highlight">예산</mark>');
      expect(result.hasMatch).toBe(true);
      expect(result.matchCount).toBe(1);
    });

    it('should handle overlapping patterns correctly', () => {
      // 'aaa' searching for 'aa' should find 1 match (non-overlapping)
      const result = highlightText('aaaa', 'aa');
      expect(result.matchCount).toBe(2);
    });
  });

  describe('custom highlight class', () => {
    it('should use custom highlight class when provided', () => {
      const result = highlightText('테스트 문장', '테스트', 'custom-highlight');
      expect(result.html).toBe(
        '<mark class="custom-highlight">테스트</mark> 문장'
      );
    });
  });
});
