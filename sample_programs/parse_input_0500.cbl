       IDENTIFICATION DIVISION.
       PROGRAM-ID. PARSE500.
      * Paragraphs 0500-PARSE-INPUT and 0570-MOVE-CONFIG-LINE, as pasted from the source.
      * The WORKING-STORAGE below is a PLACEHOLDER written only so that the program analyses:
      * the real declarations are not known yet. Items marked PLACEHOLDER should be replaced.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PARSE-SWITCHES.
           05  WS-END-OF-DATA-SW         PIC X(01) VALUE 'N'.
               88  WS-END-OF-DATA                  VALUE 'Y'.
           05  WS-DELIMITER-FOUND-SW     PIC X(01) VALUE 'N'.
               88  WS-DELIMITER-FOUND              VALUE 'Y'.
           05  WS-NO-MORE-LINES-SW       PIC X(01) VALUE 'N'.
               88  WS-NO-MORE-LINES                VALUE 'Y'.
           05  WS-ERROR-FOUND-SW         PIC X(01) VALUE 'N'.
               88  WS-ERROR-FOUND                  VALUE 'Y'.
           05  WS-PRE-ORDER-ERROR-SW     PIC X(01) VALUE 'N'.
               88  WS-PRE-ORDER-ERROR              VALUE 'Y'.
       01  WS-PARSE-POSITIONS.
           05  WS-FUNCTION               PIC X(02).
           05  WS-FUNC-LEN               PIC 9(03).
           05  WS-FUNC-LEN-N-1           PIC 9(03).
           05  WS-START-POS              PIC 9(05).
           05  WS-CHAR-POS               PIC 9(05).
           05  WS-NEXT-POS               PIC 9(05).
           05  WS-MOVE-LEN              PIC 9(05).
           05  SUB                       PIC 9(03).
       01  WS-SAVE-CNFG-LINE             PIC X(100).
       01  RCV-DATA-BUFFER-AREA          PIC X(4000).
       01  RCV-NEW-ORDER                 PIC X(02).
       01  SND-ERR-CODE                  PIC X(02).
       01  SND-ERR-TEXT                  PIC X(30).
       COPY TBIINLN.
       COPY ORRORH.
       COPY ORRORL.
       COPY ORRCNFG.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM 0500-PARSE-INPUT
           STOP RUN.
       0500-PARSE-INPUT.
           MOVE  'N'                  TO WS-END-OF-DATA-SW
                                         WS-DELIMITER-FOUND-SW.
           MOVE LENGTH OF WS-FUNCTION TO WS-FUNC-LEN.
           COMPUTE WS-FUNC-LEN-N-1 = WS-FUNC-LEN + 1.
           IF RCV-NEW-ORDER
              MOVE +1750                          TO WS-START-POS
              PERFORM 0550-FIND-NEXT-DELIMITER
              IF WS-DELIMITER-FOUND
                 MOVE WS-FUNC-LEN-N-1  TO WS-START-POS
              ELSE
                 MOVE  'N'             TO WS-END-OF-DATA-SW
                 MOVE WS-FUNC-LEN-N-1  TO WS-START-POS
                 PERFORM 0550-FIND-NEXT-DELIMITER
              END-IF
              IF WS-DELIMITER-FOUND
                 SUBTRACT WS-FUNC-LEN  FROM WS-START-POS
                 COMPUTE WS-MOVE-LEN = WS-CHAR-POS - WS-START-POS
                 IF WS-MOVE-LEN >= LENGTH OF ORRORH-ORDER-REQUEST
                    MOVE LENGTH OF ORRORH-ORDER-REQUEST TO WS-MOVE-LEN
                    INITIALIZE                    ORRORH-ORDER-REQUEST
                    MOVE RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)
                                               TO ORRORH-ORDER-REQUEST
                 ELSE
                    MOVE 'HL'                    TO SND-ERR-CODE
                    MOVE 'HEADER LENGTH ERROR'   TO SND-ERR-TEXT
                    SET WS-ERROR-FOUND           TO TRUE
                    SET WS-PRE-ORDER-ERROR       TO TRUE
                    GO TO 0500-EXIT
                 END-IF
              ELSE
                 MOVE 'HD'                    TO SND-ERR-CODE
                 MOVE 'NO HEADER DELIMITER'   TO SND-ERR-TEXT
                 SET WS-ERROR-FOUND           TO TRUE
                 SET WS-PRE-ORDER-ERROR       TO TRUE
                 GO TO 0500-EXIT
              END-IF

              MOVE ORRORH-COUNTRY-CODE        TO  TB-IL-CO-CODE
                                                  TB-IL2-CO-CODE
              MOVE ORRORH-ORDER-ENTRY-METHOD  TO  TB-IL-TERM-ID
                                                  TB-IL2-TERM-ID
              CALL 'SYU510'                   USING  TB-IL-PROC-IA
              CALL 'SYU510'                   USING  TB-IL2-PROC-IA

              COMPUTE WS-NEXT-POS = WS-CHAR-POS + 1
              MOVE RCV-DATA-BUFFER-AREA(WS-NEXT-POS:2) TO WS-FUNCTION
              EVALUATE TRUE
                 WHEN WS-FUNCTION = ('OL' OR 'CL' OR 'EC' OR 'ML' OR
                                     'PT')
                    MOVE +0 TO SUB
                    MOVE 'N'   TO WS-NO-MORE-LINES-SW
                    PERFORM UNTIL   WS-NO-MORE-LINES
                       ADD +1 TO SUB
                       COMPUTE WS-START-POS = WS-CHAR-POS +
                               LENGTH OF ORRORL-LINE-REQUEST + 1
                       MOVE 'N'      TO WS-DELIMITER-FOUND-SW
                       PERFORM 0550-FIND-NEXT-DELIMITER
                       IF WS-DELIMITER-FOUND
                          COMPUTE WS-START-POS = WS-NEXT-POS +
                                                 WS-FUNC-LEN
                       ELSE
                          COMPUTE WS-START-POS = WS-NEXT-POS +
                                                 WS-FUNC-LEN
                          MOVE  'N'         TO WS-END-OF-DATA-SW
                          PERFORM 0550-FIND-NEXT-DELIMITER
                       END-IF
                       IF WS-DELIMITER-FOUND
                          CONTINUE
                       ELSE
                          MOVE 'LD'                      TO SND-ERR-CODE
                          MOVE 'NO LINE DELIMITER ERROR' TO SND-ERR-TEXT
                          SET WS-ERROR-FOUND             TO TRUE
                          SET WS-PRE-ORDER-ERROR         TO TRUE
                          GO TO 0500-EXIT
                       END-IF
                       SUBTRACT WS-FUNC-LEN  FROM WS-START-POS
                       COMPUTE WS-MOVE-LEN = WS-CHAR-POS - WS-START-POS
                       IF WS-MOVE-LEN >= LENGTH OF ORRORL-LINE-REQUEST
                          PERFORM 0560-MOVE-LINE-OR-COMMENT
                       ELSE
                          MOVE 'LL'                      TO SND-ERR-CODE
                          MOVE 'LINE LENGTH ERROR      ' TO SND-ERR-TEXT
                          SET WS-ERROR-FOUND           TO TRUE
                          SET WS-PRE-ORDER-ERROR         TO TRUE
                          GO TO 0500-EXIT
                       END-IF
                       COMPUTE WS-NEXT-POS = WS-CHAR-POS + 1
                       MOVE RCV-DATA-BUFFER-AREA(WS-NEXT-POS:2)
                                                       TO WS-FUNCTION
                       IF WS-END-OF-DATA
                          SET WS-NO-MORE-LINES TO TRUE
                       ELSE
                          IF WS-FUNCTION = ('OL' OR 'CL' OR 'EC' OR
                                            'ML' OR 'PT')
                             CONTINUE
                          ELSE
                             SET WS-NO-MORE-LINES TO TRUE
                          END-IF
                       END-IF
                    END-PERFORM
                 WHEN WS-FUNCTION = 'CF'
                    IF TB-IL-ALLOW-CONFIG-ORDER
                       CONTINUE
                    ELSE
                       MOVE 'CF'                      TO SND-ERR-CODE
                       MOVE 'CONFIG ORDER NOT ALLOW ' TO SND-ERR-TEXT
                       SET WS-ERROR-FOUND             TO TRUE
                       SET WS-PRE-ORDER-ERROR         TO TRUE
                       GO TO 0500-EXIT
                    END-IF
                    MOVE +0 TO SUB
                    MOVE 'N'   TO WS-NO-MORE-LINES-SW
                    PERFORM UNTIL ((WS-NO-MORE-LINES) OR (SUB = +2))
                       ADD +1 TO SUB
                       COMPUTE WS-START-POS = WS-CHAR-POS +
                               LENGTH OF ORRCNFG-CNFG-REQUEST + 1
                       MOVE 'N'      TO WS-DELIMITER-FOUND-SW
                       PERFORM 0550-FIND-NEXT-DELIMITER
                       IF WS-DELIMITER-FOUND
                          COMPUTE WS-START-POS = WS-NEXT-POS +
                                                 WS-FUNC-LEN
                       ELSE
                          COMPUTE WS-START-POS = WS-NEXT-POS +
                                                 WS-FUNC-LEN
                          MOVE  'N'         TO WS-END-OF-DATA-SW
                          PERFORM 0550-FIND-NEXT-DELIMITER
                       END-IF
                       IF WS-DELIMITER-FOUND
                          CONTINUE
                       ELSE
                          MOVE 'LD'                      TO SND-ERR-CODE
                          MOVE 'NO LINE DELIMITER ERROR' TO SND-ERR-TEXT
                          SET WS-ERROR-FOUND             TO TRUE
                          SET WS-PRE-ORDER-ERROR         TO TRUE
                          GO TO 0500-EXIT
                       END-IF
                       SUBTRACT WS-FUNC-LEN  FROM WS-START-POS
                       COMPUTE WS-MOVE-LEN = WS-CHAR-POS - WS-START-POS
                       IF WS-MOVE-LEN >= LENGTH OF ORRCNFG-CNFG-REQUEST
                          PERFORM 0570-MOVE-CONFIG-LINE
                       ELSE
                          MOVE 'LL'                      TO SND-ERR-CODE
                          MOVE 'LINE LENGTH ERROR      ' TO SND-ERR-TEXT
                          SET WS-ERROR-FOUND             TO TRUE
                          SET WS-PRE-ORDER-ERROR         TO TRUE
                          GO TO 0500-EXIT
                       END-IF
                       COMPUTE WS-NEXT-POS = WS-CHAR-POS + 1
                       MOVE RCV-DATA-BUFFER-AREA(WS-NEXT-POS:2)
                                                       TO WS-FUNCTION
                       IF WS-END-OF-DATA
                          SET WS-NO-MORE-LINES TO TRUE
                       ELSE
                          IF WS-FUNCTION = 'CF'
                             CONTINUE
                          ELSE
                             SET WS-NO-MORE-LINES TO TRUE
                          END-IF
                       END-IF
                    END-PERFORM
                 WHEN OTHER
                    SET WS-NO-MORE-LINES TO TRUE
              END-EVALUATE
           ELSE
              SET WS-ERROR-FOUND           TO TRUE
              MOVE 'NH'                      TO SND-ERR-CODE
              MOVE 'NO HEADER ERROR        ' TO SND-ERR-TEXT
              SET WS-PRE-ORDER-ERROR         TO TRUE
           END-IF.
       0500-EXIT.
           EXIT.
       0570-MOVE-CONFIG-LINE.
           MOVE LENGTH OF ORRCNFG-CNFG-REQUEST TO WS-MOVE-LEN
           IF RCV-DATA-BUFFER-AREA(WS-START-POS:2) = 'CF'
              INITIALIZE           ORRCNFG-CNFG-REQUEST
              MOVE RCV-DATA-BUFFER-AREA(WS-START-POS:WS-MOVE-LEN)
                                   TO ORRCNFG-CNFG-REQUEST
              MOVE ORRCNFG-CNFG-REQUEST   TO WS-SAVE-CNFG-LINE (SUB)
           END-IF.
